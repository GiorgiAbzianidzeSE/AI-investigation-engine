import pytest

from app.config import Settings
from app.ingest.pipeline import DocumentExists, DocumentNotFound, IngestPipeline, ProtectedDocument
from tests.fakes import FakeEmbedder, FakeStore

ARCH = (b"# Payments architecture\n\nThe payments-gateway calls fraud-scorer synchronously on 2026-03-01.\n\n"
        b"## Ledger\n\nledger-service keeps a connection pool to the ledger DB.")


@pytest.fixture
def pipe():
    return IngestPipeline(FakeStore(), FakeEmbedder(), Settings(_env_file=None, chunk_words=20, chunk_overlap=5))


def test_add_indexes_both_strategies(pipe):
    r = pipe.add_file("payments-architecture.md", ARCH, source="incidents")
    assert r.status == "added" and r.version == 1
    assert r.doc_id == "incidents:payments-architecture-md"
    strategies = {c["payload"]["strategy"] for c in pipe.store.chunks.values()}
    assert strategies == {"a", "b"}
    doc = pipe.store.get_document(r.doc_id)
    assert doc["chunk_count"]["a"] >= 1 and doc["chunk_count"]["b"] >= 2
    assert doc["format"] == "md" and doc["date"] == "2026-03-01"


def test_same_content_is_duplicate(pipe):
    pipe.add_file("payments-architecture.md", ARCH)
    r = pipe.add_file("copy.md", ARCH.replace(b"  ", b" ").upper())
    assert r.status == "duplicate"
    assert r.duplicate_of == "upload:payments-architecture-md"
    assert pipe.store.get_document("upload:copy-md") is None


def test_same_filename_without_replace_conflicts(pipe):
    pipe.add_file("a.md", ARCH)
    with pytest.raises(DocumentExists):
        pipe.add_file("a.md", ARCH + b"\n\nNew line.")


def test_replace_bumps_version_and_drops_old_chunks(pipe):
    first = pipe.add_file("a.md", ARCH)
    created = pipe.store.get_document(first.doc_id)["created_at"]
    r = pipe.add_file("a.md", b"# Totally new\n\nDifferent body text only.", replace=True)
    assert r.status == "updated" and r.version == 2
    texts = " ".join(c["payload"]["text"] for c in pipe.store.chunks.values())
    assert "fraud-scorer" not in texts and "Different body" in texts
    assert pipe.store.get_document(r.doc_id)["created_at"] == created


def test_near_duplicate_is_flagged_but_indexed(pipe):
    pipe.add_file("payments-architecture.md", ARCH, source="incidents")
    r = pipe.add_file("payments-architecture-v2.md", ARCH + b"\n\nLast reviewed: 2026-03-28")
    assert r.status == "added"
    assert r.near_duplicate_of == "incidents:payments-architecture-md"


def test_delete_rules(pipe):
    pipe.add_file("corpus.md", ARCH, source="incidents")
    with pytest.raises(ProtectedDocument):
        pipe.delete("incidents:corpus-md")
    with pytest.raises(DocumentNotFound):
        pipe.delete("upload:nope")
    r = pipe.add_file("mine.md", b"# Mine\n\nSomething unrelated entirely.")
    pipe.delete(r.doc_id)
    assert pipe.store.get_document(r.doc_id) is None
    assert not any(c["payload"]["doc_id"] == r.doc_id for c in pipe.store.chunks.values())


def test_bulk_records_resume(pipe):
    recs = [{"doc_id": f"hp:{i}", "title": f"T{i}", "text": f"paragraph {i} text"} for i in range(5)]
    assert pipe.add_records(recs[:3]) == 3
    assert pipe.add_records(recs) == 2
    assert {c["payload"]["strategy"] for c in pipe.store.chunks.values()} == {"na"}
    assert pipe.store.count_documents() == 5
