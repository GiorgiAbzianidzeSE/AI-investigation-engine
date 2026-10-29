"""Tools the model can call during the investigation phase, plus the run's evidence set.

Every chunk a tool returns is recorded in the evidence set; only those chunks can be cited later.
"""
import json
from dataclasses import dataclass

from app.search.hybrid import strategies_for
from app.search.store import Hit

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_corpus",
        "description": "Hybrid (semantic + keyword) search over all documents. Returns the top chunks.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "short, specific search query"},
            "doc_ids": {"type": "array", "items": {"type": "string"},
                        "description": "optional: only search inside these documents"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "get_document",
        "description": "Read a document: its metadata and its first chunks.",
        "parameters": {"type": "object", "properties": {
            "doc_id": {"type": "string", "description": "doc_id from a search result"},
        }, "required": ["doc_id"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Stop searching: every sub-question has evidence, or more searching will not help.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"},
        }, "required": ["reason"]},
    }},
]

SNIPPET_CHARS = 700
DOC_CHUNKS = 6


@dataclass
class EvidenceItem:
    hit: Hit
    order: int
    seen: int = 1


class Toolbox:
    def __init__(self, searcher, store, strategy: str, mode: str, top_k: int = 8):
        self.searcher, self.store = searcher, store
        self.strategy, self.mode, self.top_k = strategy, mode, top_k
        self.evidence: dict[str, EvidenceItem] = {}

    def run(self, name: str, args: dict) -> tuple[str, int]:
        """Execute one tool call. Returns (JSON text for the model, number of chunks returned)."""
        try:
            if name == "search_corpus":
                hits = self.search_corpus(str(args.get("query", "")), args.get("doc_ids") or None)
                return json.dumps([_brief(h) for h in hits]), len(hits)
            if name == "get_document":
                doc, hits = self.get_document(str(args.get("doc_id", "")))
                if doc is None:
                    return json.dumps({"error": f"unknown doc_id {args.get('doc_id')!r}"}), 0
                meta = {k: doc.get(k) for k in ("doc_id", "title", "source", "format", "doc_type", "date")}
                return json.dumps({"document": meta, "chunks": [_brief(h) for h in hits]}), len(hits)
            return json.dumps({"error": f"unknown tool {name!r}"}), 0
        except (TypeError, ValueError) as e:
            return json.dumps({"error": f"bad arguments: {e}"}), 0

    def search_corpus(self, query: str, doc_ids: list[str] | None = None) -> list[Hit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        hits = self.searcher.search(query, strategy=self.strategy, mode=self.mode, top_k=self.top_k,
                                    doc_ids=doc_ids)
        self._record(hits)
        return hits

    def get_document(self, doc_id: str) -> tuple[dict | None, list[Hit]]:
        doc = self.store.get_document(doc_id)
        if doc is None:
            return None, []
        hits = self.store.get_chunks(doc_id, strategies_for(self.strategy), limit=DOC_CHUNKS)
        self._record(hits)
        return doc, hits

    def _record(self, hits: list[Hit]) -> None:
        for h in hits:
            if h.chunk_id in self.evidence:
                self.evidence[h.chunk_id].seen += 1
            else:
                self.evidence[h.chunk_id] = EvidenceItem(h, len(self.evidence))

    def for_synthesis(self, limit: int) -> list[Hit]:
        """The evidence shown to the final step: chunks found most often first, then in discovery order."""
        items = sorted(self.evidence.values(), key=lambda e: (-e.seen, e.order))[:limit]
        return [e.hit for e in sorted(items, key=lambda e: e.order)]


def _brief(h: Hit) -> dict:
    return {"chunk_id": h.chunk_id, "doc_id": h.doc_id, "title": h.title, "date": h.payload.get("date"),
            "text": h.text[:SNIPPET_CHARS]}
