# 03 — Retrieval

## Embeddings (`search/embedder.py`)

- Dense: `fastembed.TextEmbedding("BAAI/bge-small-en-v1.5")`; `passage_embed` for chunks, `query_embed` for queries.
- Sparse: `fastembed.SparseTextEmbedding("Qdrant/bm25")`; `embed` for chunks, `query_embed` for queries.
- Model files cached in `models/` (configurable). The Docker build pre-downloads them.
- `embed_query` is wrapped in an LRU cache (1024 entries); cache stats appear in `/health`.

## Qdrant layout (`search/store.py`)

**Collection `chunks`**
- Named dense vector `dense`: size 384, cosine.
- Named sparse vector `bm25` with `modifier = IDF` (Qdrant computes IDF, so this is real BM25 scoring).
- `on_disk_payload = true` (fits the 1 GB free tier).
- Keyword payload indexes: `doc_id`, `strategy`, `source`.
- Point id = UUIDv5 of `chunk_id` (re-ingesting is idempotent).

**Collection `documents`** (registry)
- One point per document, payload = metadata from 02. Qdrant requires a vector, so use a 1-d dummy vector.
- Keyword indexes: `doc_id`, `source`, `content_hash`, `format`; full-text index on `title` (for the UI search box).
- Point id = UUIDv5 of `doc_id`.

Store methods: `ensure_collections, upsert_chunks, upsert_documents, delete_document, delete_chunks,
get_document, find_by_hash, list_documents, count_documents, get_chunks, dense_search, sparse_search, ping`.
Search methods accept a `strategies` filter (`[strategy, "na"]`) and an optional `doc_ids` filter.

## Hybrid search (`search/hybrid.py`)

`search(query, strategy="b", mode="full", top_k=8, doc_ids=None)`:

1. Embed the query (dense + sparse, cached).
2. Run **dense** and **BM25** queries **separately**, 50 candidates each, filtered to `[strategy, "na"]`.
3. Pass both ranked lists to our ranker.

`mode` exists so the evaluation can compare configurations:
`dense` (dense only) · `sparse` (BM25 only) · `rrf` (plain fusion) · `full` (fusion + our boosts, the default).

## Our ranking algorithm (`search/ranker.py`) — the "custom component"

```
score(c) = w_rrf · RRF_norm(c) + w_bridge · bridge(c) + w_query · query_match(c)
defaults:  w_rrf = 1.0,         w_bridge = 0.3,       w_query = 0.2
```

1. **Reciprocal Rank Fusion**: `RRF(c) = Σ_lists 1 / (60 + rank_list(c))`, normalized by the max.
   Rank-based, so the incompatible cosine and BM25 score scales are never mixed directly.
2. **Bridge score (multi-hop signal)**: take the top 30 candidates by RRF. Extract cheap entities from each
   (title; IDs like `CHG-0314` / `INC-2041`; kebab-case service names like `payments-gateway`; ISO dates;
   capitalized phrases minus stop-words), lowercased. `bridge(c)` = the number of c's entities that also
   appear in candidates from **other documents**, normalized by the max. A chunk that connects documents
   (a change ID cited in an incident report; a person named in two Wikipedia paragraphs) moves up. That is
   exactly the chunk a multi-hop question needs.
3. **Query match**: share of the query's entities found in the chunk; a match in the title counts double;
   capped at 1.0.
4. **Diversity**: at most 3 chunks per document in the final top-K, so one long document can't fill the list.

Requirements:
- Pure functions, no I/O; unit-tested with hand-made hits (see 08).
- Weights live in config; README explains each term and how the weights were picked
  (small manual sweep on 10 eval questions, results noted in EVALUATION.md).
- Entity extraction is regex-based on purpose: cheap, deterministic, explainable. No extra LLM call.
