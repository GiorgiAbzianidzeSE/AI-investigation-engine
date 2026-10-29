"""Add / update / delete documents. Used by the API (uploads) and by the offline ingest scripts."""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings
from app.ingest.chunking import chunk
from app.ingest.normalize import content_hash, slugify
from app.ingest.parsers import ParsedDocument, parse_file

log = logging.getLogger(__name__)

FILE_STRATEGIES = ("a", "b")


class DocumentExists(Exception):
    def __init__(self, doc_id: str):
        super().__init__(f"Document {doc_id} already exists; upload with replace=true to update it")
        self.doc_id = doc_id


class DocumentNotFound(Exception):
    pass


class ProtectedDocument(Exception):
    pass


@dataclass
class IngestResult:
    status: str  # added | updated | duplicate
    doc_id: str
    chunks: int = 0
    duplicate_of: str | None = None
    near_duplicate_of: str | None = None
    version: int = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_chunk_payloads(doc: dict, text: str, strategies, settings: Settings) -> list[dict]:
    payloads = []
    for strategy in strategies:
        for c in chunk(text, doc["title"], strategy, settings.chunk_words, settings.chunk_overlap):
            payloads.append({
                "chunk_id": f"{doc['doc_id']}#{strategy}{c.index}",
                "doc_id": doc["doc_id"], "title": doc["title"], "text": c.text,
                "heading": c.heading, "index": c.index, "strategy": strategy,
                "source": doc["source"], "format": doc["format"], "doc_type": doc["doc_type"],
                "date": doc.get("date"),
            })
    return payloads


class IngestPipeline:
    def __init__(self, store, embedder, settings: Settings):
        self.store, self.embedder, self.s = store, embedder, settings

    def add_file(self, filename: str, data: bytes, source: str = "upload", replace: bool = False) -> IngestResult:
        parsed = parse_file(filename, data)
        doc_id = f"{source}:{slugify(filename)}"
        return self.add_parsed(doc_id, filename, parsed, source, replace)

    def add_parsed(self, doc_id: str, filename: str, parsed: ParsedDocument, source: str,
                   replace: bool = False) -> IngestResult:
        h = content_hash(parsed.text)
        same = self.store.find_by_hash(h)
        if same:
            # identical content already indexed (under this or another id) -> nothing to do
            return IngestResult("duplicate", doc_id, duplicate_of=same["doc_id"], version=same.get("version", 1))

        existing = self.store.get_document(doc_id)
        if existing and not replace:
            raise DocumentExists(doc_id)
        version = existing["version"] + 1 if existing else 1

        doc = {
            "doc_id": doc_id, "title": parsed.title, "filename": filename, "source": source,
            "format": parsed.format, "doc_type": parsed.doc_type, "date": parsed.date,
            "content_hash": h, "version": version, "chars": len(parsed.text),
            "created_at": existing["created_at"] if existing else _now(), "updated_at": _now(),
        }
        payloads = build_chunk_payloads(doc, parsed.text, FILE_STRATEGIES, self.s)
        dense, sparse = self.embedder.embed_passages([p["text"] for p in payloads])

        near = self._near_duplicate(doc_id, [d for d, p in zip(dense, payloads) if p["strategy"] == "a"])
        doc["near_duplicate_of"] = near
        doc["chunk_count"] = {s: sum(p["strategy"] == s for p in payloads) for s in FILE_STRATEGIES}

        if existing:
            self.store.delete_chunks(doc_id)
        self.store.upsert_chunks(payloads, dense, sparse)
        self.store.upsert_documents([doc])
        log.info("ingested %s v%s (%d chunks)", doc_id, version, len(payloads))
        return IngestResult("updated" if existing else "added", doc_id, len(payloads),
                            near_duplicate_of=near, version=version)

    def add_records(self, records: list[dict], source: str = "hotpotqa") -> int:
        """Bulk path for short pre-parsed records ({doc_id, title, text}); indexed once as strategy "na".
        Records whose doc_id is already registered are skipped, so an interrupted run can resume."""
        present = self.store.existing_doc_ids([r["doc_id"] for r in records])
        todo = [r for r in records if r["doc_id"] not in present]
        if not todo:
            return 0
        now, docs, payloads = _now(), [], []
        for r in todo:
            doc = {
                "doc_id": r["doc_id"], "title": r["title"], "filename": None, "source": source,
                "format": "txt", "doc_type": "wiki", "date": None,
                "content_hash": content_hash(f"{r['title']}\n{r['text']}"), "version": 1,
                "chars": len(r["text"]), "near_duplicate_of": None, "created_at": now, "updated_at": now,
            }
            chunk_payloads = build_chunk_payloads(doc, r["text"], ("na",), self.s)
            doc["chunk_count"] = {"na": len(chunk_payloads)}
            docs.append(doc)
            payloads += chunk_payloads
        dense, sparse = self.embedder.embed_passages([f"{p['title']}: {p['text']}" for p in payloads])
        self.store.upsert_chunks(payloads, dense, sparse)
        self.store.upsert_documents(docs)
        return len(todo)

    def _near_duplicate(self, doc_id: str, vectors: list[list[float]], probe: int = 3) -> str | None:
        """Flag (don't drop) a document whose chunks are near-identical to another document's chunks."""
        for vec in vectors[:probe]:
            for hit in self.store.dense_search(vec, 3, ["a", "na"]):
                if hit.doc_id != doc_id and hit.score >= self.s.near_dup_threshold:
                    return hit.doc_id
        return None

    def delete(self, doc_id: str) -> None:
        doc = self.store.get_document(doc_id)
        if not doc:
            raise DocumentNotFound(doc_id)
        if doc["source"] != "upload":
            raise ProtectedDocument(f"{doc_id} is part of the base corpus and cannot be deleted from the API")
        self.store.delete_document(doc_id)
