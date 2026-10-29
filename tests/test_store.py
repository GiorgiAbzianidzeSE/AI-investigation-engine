"""QdrantStore against qdrant-client's local in-memory mode (no server, no network)."""
from qdrant_client import QdrantClient

from app.config import Settings
from app.ingest.pipeline import IngestPipeline
from app.search.store import QdrantStore
from tests.fakes import DIM, FakeEmbedder


def make_store():
    s = Settings(_env_file=None, dense_dim=DIM, chunk_words=20, chunk_overlap=5)
    store = QdrantStore(s, client=QdrantClient(":memory:"))
    store.ensure_collections()
    return store, s


def test_roundtrip_search_and_delete():
    store, s = make_store()
    pipe = IngestPipeline(store, FakeEmbedder(), s)
    r = pipe.add_file("runbook.md", b"# Fraud runbook\n\nRoll back the fraud-scorer model version.")
    pipe.add_records([{"doc_id": "hp:1", "title": "Paris", "text": "Paris is the capital of France."}])

    assert store.count_documents() == 2
    assert store.existing_doc_ids(["hp:1", "hp:2"]) == {"hp:1"}
    assert store.find_by_hash(store.get_document(r.doc_id)["content_hash"])["doc_id"] == r.doc_id

    emb = FakeEmbedder()
    dense, sparse = emb.embed_query("fraud-scorer rollback")
    hits = store.dense_search(dense, 5, ["b", "na"])
    assert hits[0].doc_id == r.doc_id and all(h.payload["strategy"] in ("b", "na") for h in hits)
    assert store.sparse_search(emb.embed_query("capital France")[1], 5, ["a", "na"])[0].doc_id == "hp:1"
    assert {h.doc_id for h in store.dense_search(dense, 5, None, ["hp:1"])} == {"hp:1"}

    chunks = store.get_chunks(r.doc_id, ["a"])
    assert chunks and all(c.payload["strategy"] == "a" for c in chunks)

    items, _ = store.list_documents(source="upload", q=None, limit=10, offset=None)
    assert [d["doc_id"] for d in items] == [r.doc_id]

    store.delete_document(r.doc_id)
    assert store.get_document(r.doc_id) is None
    assert store.get_chunks(r.doc_id) == []
    assert store.ping()
