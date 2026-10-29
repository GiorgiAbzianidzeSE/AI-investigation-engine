from app.config import Settings
from app.search.ranker import RankWeights, rank
from app.search.store import Hit


def strategies_for(strategy: str) -> list[str]:
    """HotpotQA records are indexed once ("na"); file documents exist per chunking strategy."""
    return [strategy, "na"]


class HybridSearcher:
    def __init__(self, store, embedder, settings: Settings):
        self.store, self.embedder, self.s = store, embedder, settings
        self.weights = RankWeights(
            rrf_k=settings.rrf_k, w_rrf=settings.w_rrf, w_bridge=settings.w_bridge,
            w_query=settings.w_query, max_per_doc=settings.max_chunks_per_doc,
        )

    def search(self, query: str, strategy: str | None = None, mode: str = "full",
               top_k: int | None = None, doc_ids: list[str] | None = None) -> list[Hit]:
        strategies = strategies_for(strategy or self.s.default_strategy)
        dense_vec, sparse_vec = self.embedder.embed_query(query)
        k = self.s.candidates_k
        dense = self.store.dense_search(dense_vec, k, strategies, doc_ids) if mode != "sparse" else []
        sparse = self.store.sparse_search(sparse_vec, k, strategies, doc_ids) if mode != "dense" else []
        return rank(query, dense, sparse, top_k or self.s.top_k, self.weights, mode)
