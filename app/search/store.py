"""Qdrant access. This is the only module that imports qdrant_client.

Collections:
  chunks    — one point per chunk: named vectors "dense" + sparse "bm25", payload with ids/text/metadata
  documents — one point per document (registry); a 1-d dummy vector because Qdrant points need one
"""
import uuid
from dataclasses import dataclass, field

from qdrant_client import QdrantClient, models

from app.config import Settings


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    score: float = 0.0
    payload: dict = field(default_factory=dict)


def point_id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


def _strategy_filter(strategies: list[str] | None, doc_ids: list[str] | None = None) -> models.Filter | None:
    must = []
    if strategies:
        must.append(models.FieldCondition(key="strategy", match=models.MatchAny(any=strategies)))
    if doc_ids:
        must.append(models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids)))
    return models.Filter(must=must) if must else None


def _to_hit(point) -> Hit:
    p = point.payload or {}
    score = getattr(point, "score", None) or 0.0  # scroll() returns Records without a score
    return Hit(p["chunk_id"], p["doc_id"], p.get("title", ""), p.get("text", ""), score, p)


class QdrantStore:
    def __init__(self, settings: Settings, client: QdrantClient | None = None):
        self.s = settings
        if client is None:
            client = (QdrantClient(path=settings.qdrant_path) if settings.qdrant_path
                      else QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=60))
        self.client = client

    # ---------- setup ----------
    def ensure_collections(self) -> None:
        c, s = self.client, self.s
        if not c.collection_exists(s.chunks_collection):
            c.create_collection(
                s.chunks_collection,
                vectors_config={"dense": models.VectorParams(size=s.dense_dim, distance=models.Distance.COSINE)},
                sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
                on_disk_payload=True,
            )
            for f in ("doc_id", "strategy", "source"):
                c.create_payload_index(s.chunks_collection, f, models.PayloadSchemaType.KEYWORD)
        if not c.collection_exists(s.documents_collection):
            c.create_collection(
                s.documents_collection,
                vectors_config=models.VectorParams(size=1, distance=models.Distance.DOT),
            )
            for f in ("doc_id", "source", "content_hash", "format"):
                c.create_payload_index(s.documents_collection, f, models.PayloadSchemaType.KEYWORD)
            c.create_payload_index(s.documents_collection, "title", models.PayloadSchemaType.TEXT)

    # ---------- writes ----------
    def upsert_chunks(self, payloads: list[dict], dense: list[list[float]], sparse: list[tuple]) -> None:
        points = [
            models.PointStruct(
                id=point_id(p["chunk_id"]),
                vector={"dense": d, "bm25": models.SparseVector(indices=sp[0], values=sp[1])},
                payload=p,
            )
            for p, d, sp in zip(payloads, dense, sparse)
        ]
        self.client.upsert(self.s.chunks_collection, points=points, wait=True)

    def upsert_documents(self, docs: list[dict]) -> None:
        points = [models.PointStruct(id=point_id(d["doc_id"]), vector=[1.0], payload=d) for d in docs]
        self.client.upsert(self.s.documents_collection, points=points, wait=True)

    def delete_document(self, doc_id: str) -> None:
        sel = models.FilterSelector(filter=_doc_filter(doc_id))
        self.client.delete(self.s.chunks_collection, points_selector=sel, wait=True)
        self.client.delete(self.s.documents_collection, points_selector=sel, wait=True)

    def delete_chunks(self, doc_id: str) -> None:
        sel = models.FilterSelector(filter=_doc_filter(doc_id))
        self.client.delete(self.s.chunks_collection, points_selector=sel, wait=True)

    # ---------- reads ----------
    def get_document(self, doc_id: str) -> dict | None:
        res = self.client.retrieve(self.s.documents_collection, ids=[point_id(doc_id)], with_payload=True)
        return res[0].payload if res else None

    def existing_doc_ids(self, doc_ids: list[str]) -> set[str]:
        res = self.client.retrieve(self.s.documents_collection, ids=[point_id(d) for d in doc_ids],
                                   with_payload=["doc_id"])
        return {p.payload["doc_id"] for p in res}

    def find_by_hash(self, h: str) -> dict | None:
        f = models.Filter(must=[models.FieldCondition(key="content_hash", match=models.MatchValue(value=h))])
        points, _ = self.client.scroll(self.s.documents_collection, scroll_filter=f, limit=1, with_payload=True)
        return points[0].payload if points else None

    def list_documents(self, source: str | None, q: str | None, limit: int, offset: str | None):
        must = []
        if source:
            must.append(models.FieldCondition(key="source", match=models.MatchValue(value=source)))
        if q:
            must.append(models.FieldCondition(key="title", match=models.MatchText(text=q)))
        points, nxt = self.client.scroll(
            self.s.documents_collection, scroll_filter=models.Filter(must=must) if must else None,
            limit=limit, offset=offset, with_payload=True,
        )
        return [p.payload for p in points], (str(nxt) if nxt else None)

    def count_documents(self) -> int:
        return self.client.count(self.s.documents_collection, exact=False).count

    def count_chunks(self, strategy: str | None = None) -> int:
        f = _strategy_filter([strategy]) if strategy else None
        return self.client.count(self.s.chunks_collection, count_filter=f, exact=True).count

    def get_chunks(self, doc_id: str, strategies: list[str] | None = None, limit: int = 200) -> list[Hit]:
        f = _doc_filter(doc_id)
        if strategies:
            f.must.append(models.FieldCondition(key="strategy", match=models.MatchAny(any=strategies)))
        points, _ = self.client.scroll(self.s.chunks_collection, scroll_filter=f, limit=limit, with_payload=True)
        return sorted((_to_hit(p) for p in points), key=lambda h: h.payload.get("index", 0))

    def dense_search(self, vector: list[float], k: int, strategies: list[str] | None = None,
                     doc_ids: list[str] | None = None) -> list[Hit]:
        res = self.client.query_points(
            self.s.chunks_collection, query=vector, using="dense",
            query_filter=_strategy_filter(strategies, doc_ids), limit=k, with_payload=True,
        )
        return [_to_hit(p) for p in res.points]

    def sparse_search(self, sparse: tuple, k: int, strategies: list[str] | None = None,
                      doc_ids: list[str] | None = None) -> list[Hit]:
        res = self.client.query_points(
            self.s.chunks_collection, query=models.SparseVector(indices=sparse[0], values=sparse[1]),
            using="bm25", query_filter=_strategy_filter(strategies, doc_ids), limit=k, with_payload=True,
        )
        return [_to_hit(p) for p in res.points]

    def ping(self) -> bool:
        self.client.get_collections()
        return True
