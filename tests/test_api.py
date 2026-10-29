import pytest
from fastapi.testclient import TestClient

from app.api.main import Services, app, get_services
from app.config import Settings
from app.ingest.pipeline import IngestPipeline
from app.investigate.agent import Investigator
from app.llm.provider import LLMUnavailable
from app.search.hybrid import HybridSearcher
from tests.fakes import FakeEmbedder, FakeLLM, FakeStore, tool_call

S = Settings(_env_file=None, admin_token="secret", chunk_words=40, chunk_overlap=5)
AUTH = {"X-Admin-Token": "secret"}


def services(replies=()):
    store, emb = FakeStore(), FakeEmbedder()
    pipe = IngestPipeline(store, emb, S)
    pipe.add_file("inc.md", b"# INC-2041\n\nCHG-0314 slowed fraud-scorer on 2026-03-05.", source="incidents")
    llm = FakeLLM(list(replies))
    agent = Investigator(llm, HybridSearcher(store, emb, S), store, S)
    return Services(S, store, emb, pipe, llm, agent)


@pytest.fixture
def client():
    svc = services()
    app.dependency_overrides[get_services] = lambda: svc
    yield TestClient(app), svc
    app.dependency_overrides.clear()


def test_health_and_index(client):
    c, _ = client
    h = c.get("/health").json()
    assert h["qdrant"] == "ok" and h["documents"] == 1 and h["llm_providers"] == ["fake"]
    assert "AI Investigation Engine" in c.get("/").text


def test_investigate_returns_contract(client):
    c, svc = client
    cid = next(k for k, v in svc.store.chunks.items() if v["payload"]["strategy"] == "b")
    svc.llm.replies = [{"tool_calls": [tool_call("search_corpus", query="INC-2041")]},
                       {"tool_calls": [tool_call("finish", reason="ok")]},
                       {"content": {"status": "answered", "answer": "CHG-0314",
                                    "claims": [{"text": "CHG-0314 slowed fraud-scorer", "citations": [cid]}]}}]
    r = c.post("/investigate", json={"question": "What caused INC-2041?"})
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "answer", "claims", "conflicts", "missing", "sources", "trace", "usage", "config"):
        assert key in body
    assert body["status"] == "answered" and body["sources"][0]["chunk_id"] == cid


def test_investigate_validation(client):
    c, _ = client
    assert c.post("/investigate", json={"question": "  "}).status_code == 422
    assert c.post("/investigate", json={"question": "x" * 501}).status_code == 422
    r = c.post("/investigate", json={"question": "ok?", "mode": "magic"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_config"
    assert c.post("/investigate", json={}).json()["error"] == "invalid_request"


def test_llm_down_is_503(client):
    c, svc = client
    svc.llm.replies = [LLMUnavailable("429 everywhere")]
    r = c.post("/investigate", json={"question": "What caused INC-2041?"})
    assert r.status_code == 503 and r.json()["error"] == "llm_unavailable"


def test_no_llm_configured_is_503(client):
    c, svc = client
    svc.agent = None
    assert c.post("/investigate", json={"question": "q"}).status_code == 503


def test_upload_requires_token(client):
    c, _ = client
    files = {"file": ("a.md", b"# A\n\nbody text")}
    assert c.post("/documents", files=files).status_code == 401
    assert c.post("/documents", files=files, headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.delete("/documents/upload:a-md").status_code == 401


def test_upload_replace_duplicate_delete_flow(client):
    c, _ = client
    r = c.post("/documents", files={"file": ("a.md", b"# A\n\nfirst body")}, headers=AUTH).json()
    assert r["status"] == "added" and r["doc_id"] == "upload:a-md"
    assert c.post("/documents", files={"file": ("a.md", b"# A\n\nsecond")}, headers=AUTH).status_code == 409
    r = c.post("/documents", files={"file": ("a.md", b"# A\n\nsecond")}, data={"replace": "true"}, headers=AUTH)
    assert r.json()["status"] == "updated" and r.json()["version"] == 2
    dup = c.post("/documents", files={"file": ("copy.md", b"# A\n\nsecond")}, headers=AUTH).json()
    assert dup["status"] == "duplicate" and dup["duplicate_of"] == "upload:a-md"

    doc = c.get("/documents/upload:a-md?strategy=a").json()
    assert doc["document"]["version"] == 2 and all(ch["strategy"] == "a" for ch in doc["chunks"])
    listed = c.get("/documents?source=upload").json()
    assert [d["doc_id"] for d in listed["items"]] == ["upload:a-md"]

    assert c.delete("/documents/upload:a-md", headers=AUTH).json() == {"deleted": "upload:a-md"}
    assert c.get("/documents/upload:a-md").status_code == 404
    assert c.delete("/documents/upload:a-md", headers=AUTH).status_code == 404


def test_upload_errors(client):
    c, _ = client
    assert c.post("/documents", files={"file": ("x.exe", b"MZ")}, headers=AUTH).status_code == 415
    assert c.post("/documents", files={"file": ("e.txt", b"   ")}, headers=AUTH).status_code == 422
    assert c.post("/documents", files={"file": ("bad.pdf", b"not a pdf")}, headers=AUTH).status_code == 422
    big = b"a" * (10 * 1024 * 1024 + 1)
    assert c.post("/documents", files={"file": ("big.txt", big)}, headers=AUTH).status_code == 413


def test_cannot_delete_corpus_document(client):
    c, _ = client
    r = c.delete("/documents/incidents:inc-md", headers=AUTH)
    assert r.status_code == 403 and r.json()["error"] == "protected"


def test_store_down_is_503(client):
    import httpx

    c, svc = client

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    svc.store.list_documents = boom
    svc.store.ping = boom
    r = c.get("/documents")
    assert r.status_code == 503 and r.json()["error"] == "store_unavailable"
    assert c.get("/health").json()["qdrant"] == "error"
