"""In-memory stand-ins for Qdrant, the embedder and the LLM. No network in unit tests."""
import hashlib
import json
import math
import re
from types import SimpleNamespace

from app.search.store import Hit

DIM = 64


def _hash_vec(text: str) -> list[float]:
    """Bag-of-words hashed into DIM buckets, L2-normalized: similar texts get similar vectors."""
    v = [0.0] * DIM
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _sparse(text: str) -> tuple[list[int], list[float]]:
    counts: dict[int, float] = {}
    for w in re.findall(r"\w+", text.lower()):
        i = int(hashlib.md5(w.encode()).hexdigest(), 16) % 100_000
        counts[i] = counts.get(i, 0.0) + 1.0
    return list(counts), list(counts.values())


class FakeEmbedder:
    def __init__(self):
        self.query_calls = 0

    def embed_passages(self, texts, batch_size=64):
        return [_hash_vec(t) for t in texts], [_sparse(t) for t in texts]

    def embed_query(self, query):
        self.query_calls += 1
        return _hash_vec(query), _sparse(query)

    def query_cache_info(self):
        return SimpleNamespace(hits=0, misses=self.query_calls, maxsize=0, currsize=0)


class FakeStore:
    def __init__(self):
        self.chunks: dict[str, dict] = {}  # chunk_id -> {"payload", "dense", "sparse"}
        self.docs: dict[str, dict] = {}

    def ensure_collections(self):
        pass

    def upsert_chunks(self, payloads, dense, sparse):
        for p, d, s in zip(payloads, dense, sparse):
            self.chunks[p["chunk_id"]] = {"payload": dict(p), "dense": d, "sparse": dict(zip(*s))}

    def upsert_documents(self, docs):
        for d in docs:
            self.docs[d["doc_id"]] = dict(d)

    def delete_document(self, doc_id):
        self.delete_chunks(doc_id)
        self.docs.pop(doc_id, None)

    def delete_chunks(self, doc_id):
        for cid in [c for c, v in self.chunks.items() if v["payload"]["doc_id"] == doc_id]:
            del self.chunks[cid]

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def existing_doc_ids(self, doc_ids):
        return {d for d in doc_ids if d in self.docs}

    def find_by_hash(self, h):
        return next((d for d in self.docs.values() if d.get("content_hash") == h), None)

    def list_documents(self, source=None, q=None, limit=50, offset=None):
        items = [d for d in self.docs.values()
                 if (not source or d["source"] == source) and (not q or q.lower() in d["title"].lower())]
        start = int(offset or 0)
        nxt = str(start + limit) if start + limit < len(items) else None
        return items[start:start + limit], nxt

    def count_documents(self):
        return len(self.docs)

    def count_chunks(self, strategy=None):
        return sum(1 for v in self.chunks.values() if not strategy or v["payload"]["strategy"] == strategy)

    def get_chunks(self, doc_id, strategies=None, limit=200):
        hits = [self._hit(v, 0.0) for v in self.chunks.values()
                if v["payload"]["doc_id"] == doc_id and (not strategies or v["payload"]["strategy"] in strategies)]
        return sorted(hits, key=lambda h: h.payload["index"])[:limit]

    def _candidates(self, strategies, doc_ids):
        return [v for v in self.chunks.values()
                if (not strategies or v["payload"]["strategy"] in strategies)
                and (not doc_ids or v["payload"]["doc_id"] in doc_ids)]

    def dense_search(self, vector, k, strategies=None, doc_ids=None):
        scored = [(sum(a * b for a, b in zip(vector, v["dense"])), v) for v in self._candidates(strategies, doc_ids)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._hit(v, s) for s, v in scored[:k]]

    def sparse_search(self, sparse, k, strategies=None, doc_ids=None):
        q = dict(zip(*sparse))
        scored = [(sum(q[i] * v["sparse"].get(i, 0.0) for i in q), v) for v in self._candidates(strategies, doc_ids)]
        scored = [x for x in scored if x[0] > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._hit(v, s) for s, v in scored[:k]]

    def ping(self):
        return True

    @staticmethod
    def _hit(v, score):
        p = v["payload"]
        return Hit(p["chunk_id"], p["doc_id"], p.get("title", ""), p.get("text", ""), score, p)


class FakeLLM:
    """Scripted replies. Each item is an LLMReply-like dict or an exception to raise."""

    def __init__(self, replies):
        from app.llm.provider import LLMReply

        self._LLMReply = LLMReply
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.provider_names = ["fake"]

    def chat(self, messages, tools=None, json_mode=False):
        self.calls.append({"messages": messages, "tools": tools, "json_mode": json_mode})
        if not self.replies:
            raise AssertionError("FakeLLM ran out of scripted replies")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, str):
            r = {"content": r}
        if isinstance(r.get("content"), dict):
            r = {**r, "content": json.dumps(r["content"])}
        return self._LLMReply(r.get("content"), r.get("tool_calls", []), r.get("provider", "fake"), 10, 5)


def tool_call(name, **args):
    return {"id": f"call_{name}_{len(args)}", "name": name, "arguments": args}
