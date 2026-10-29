"""Local embeddings via fastembed (ONNX): dense bge-small + BM25 sparse. No API cost or rate limit."""
from functools import lru_cache

from app.config import Settings

SparseVec = tuple[list[int], list[float]]


class Embedder:
    def __init__(self, settings: Settings):
        from fastembed import SparseTextEmbedding, TextEmbedding

        self._dense = TextEmbedding(settings.dense_model, cache_dir=settings.model_cache_dir)
        self._sparse = SparseTextEmbedding(settings.sparse_model, cache_dir=settings.model_cache_dir)
        self.query_cache_info = self._embed_query.cache_info

    def embed_passages(self, texts: list[str], batch_size: int = 32) -> tuple[list[list[float]], list[SparseVec]]:
        # A batch is padded to its longest text, so embedding in length order is ~3x faster on CPU.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        sorted_texts = [texts[i] for i in order]
        dense_sorted = [v.tolist() for v in self._dense.passage_embed(sorted_texts, batch_size=batch_size)]
        dense: list[list[float]] = [[]] * len(texts)
        for pos, i in enumerate(order):
            dense[i] = dense_sorted[pos]
        sparse = [(s.indices.tolist(), s.values.tolist()) for s in self._sparse.embed(texts, batch_size=batch_size)]
        return dense, sparse

    def embed_query(self, query: str) -> tuple[list[float], SparseVec]:
        return self._embed_query(query.strip())

    @lru_cache(maxsize=1024)
    def _embed_query(self, query: str) -> tuple[list[float], SparseVec]:
        dense = next(iter(self._dense.query_embed(query))).tolist()
        s = next(iter(self._sparse.query_embed(query)))
        return dense, (s.indices.tolist(), s.values.tolist())
