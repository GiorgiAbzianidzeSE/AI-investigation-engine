# Evaluation

> **Status:** method, harness and question set are final. The result tables below come from a **development
> index** (16 incident documents + the first 2,000 of 65,000 HotpotQA records, embedded local Qdrant). Multi-hop
> retrieval is therefore 0 here: most HotpotQA gold paragraphs aren't indexed yet. Final numbers are produced by
> re-running the same commands against the full Qdrant Cloud index. E3 (end to end) needs LLM keys.

## 1. Method

**Question set** (`eval/questions.jsonl`, 42 questions, built by `eval/build_questions.py`):

| Type | n | Source | Expected status |
|---|---|---|---|
| simple | 8 | incident corpus | answered |
| multi_doc | 8 | incident corpus (incl. the brief's March question) | answered |
| multi_hop | 14 | HotpotQA, seed 42: 7 bridge + 7 comparison, only questions whose paragraphs are indexed | answered |
| unanswerable | 6 | incident corpus (deliberate gaps) | insufficient_evidence |
| contradictory | 6 | incident corpus (planted contradictions C1–C5) | conflicting_evidence |

**Gold labels.** Incident questions: written together with the corpus (`specs/appendix-b-eval-questions.md`). Each
fact lives only in the documents listed for it, so the gold documents are known by construction. Guard tests
(`tests/test_corpus.py`) check that the contradictions are planted and the gaps stay unanswered. HotpotQA: the
dataset's `answer` and the paragraphs named in `supporting_facts`.

**Metrics** (`eval/metrics.py`):

- **Recall@K** (K = 5, 10): share of gold documents among the top-K retrieved *documents* (chunks collapsed to
  their document, first occurrence keeps the rank).
- **MRR**: mean of 1 / rank of the first gold document (0 if not in the top 10).
- **Answer correctness**: answerable questions are correct when the status is `answered` and every `must_include`
  string appears (case- and punctuation-insensitive) in the answer and claims. Unanswerable questions are correct
  when the system abstains. Contradictory questions are correct when a conflict is reported **and** its citations
  cover both sides' gold documents (0.5 if only the status is right). A softer token-F1 is also reported.
- **Citation accuracy**: *precision* is the share of cited chunks whose document is a gold document; *support*
  is the share of answered questions with at least one correct citation.
- Logged per question: latency, LLM calls, tokens, agent steps, dropped citations.

Retrieval metrics skip unanswerable questions (no gold documents).

**Configurations**

| Experiment | Compares | Run |
|---|---|---|
| E1 retrieval method | dense vs BM25 vs plain RRF vs full (our ranker), chunking B | `run_eval --experiments e1` |
| E2 chunking | strategy A vs B, full ranker, incident questions | `run_eval --experiments e2` |
| E3 end to end | the agent with strategy B + full ranker (optionally A + full) | `run_eval --experiments e3` |

E1/E2 send the question text straight to `HybridSearcher.search` (single-shot), so they're cheap and
deterministic. E3 runs the full agent with the LLM cache at `eval/results/llm.cache.json`.

## 2. Results

### E1: retrieval method (dev index, chunking B, 36 questions with gold documents)

| config | recall@5 | recall@10 | MRR | MRR simple | MRR multi_doc | MRR contradictory |
|---|---|---|---|---|---|---|
| dense | 0.474 | 0.572 | 0.542 | 0.771 | 0.917 | 1.000 |
| BM25 | 0.533 | 0.594 | 0.526 | 0.938 | 0.775 | 0.875 |
| RRF | 0.506 | 0.600 | 0.510 | 0.938 | 0.754 | 0.806 |
| **full (ours)** | 0.519 | **0.606** | 0.525 | 0.854 | 0.823 | 0.917 |

### E2: chunking (dev index, full ranker, 22 incident questions)

| strategy | recall@5 | recall@10 | MRR |
|---|---|---|---|
| A, fixed 200-word windows | 0.844 | 0.982 | 0.716 |
| **B, structure-aware** | **0.850** | **0.991** | **0.860** |

B's chunks are smaller and carry a `title > heading:` prefix, so the right section of the right document ranks
first more often (MRR +0.14). A's larger windows reach about the same recall@10.

### E3: end to end

_Pending: needs the full index and LLM keys. Command: `uv run python -m eval.run_eval --experiments e3`._

| type | n | correct | F1 | citation precision | citation support | latency (s) | LLM calls | tokens |
|---|---|---|---|---|---|---|---|---|
| all | 42 | | | | | | | |

## 3. Cost and latency

_Pending E3._ Average tokens, calls and seconds per question come from `eval/results/e3-b-full.json`, with the
estimated cost at paid list prices.

## 4. Failure analysis

Found so far:

1. **Our ranker below plain RRF (fixed).** The first version scored MRR 0.39 vs 0.51 for RRF. RRF divided by its
   max is compressed (rank 10 ≈ 0.87 of rank 1), so a 0.3 bridge boost outweighed relevance. And the bridge
   counted every shared entity equally, so `ops-review-march-2026` (which lists every change and incident ID)
   jumped to rank 1 on S1, S2, S3, S6, M2, M5 and X3. Fix: min-max scaling of RRF over the pool, and
   rarity-weighted (IDF-style) bridge entities.
2. **The title bonus did nothing (fixed).** With query match capped at 1.0 per query, every chunk that merely
   mentioned `CHG-0314` got the same full score as the change request itself. Fix: a body match is worth half a
   title match.
3. **Dates didn't link (fixed).** "March 26" in S6 never matched `2026-03-26` in the incident report, and "March"
   alone matched every "March 2026" title (it lifted the status page and finance summary above the gold incident
   report). Fix: dates become a canonical `date:MM-DD` entity; lone month names are stop-words.
4. **Simple questions, ranker vs BM25 (open).** On the simple lookups BM25 alone is best (MRR 0.94 vs 0.85
   for full): the exact ID or name carries the query, and the bridge term can still lift a well-linked chunk
   from another document over the target. A fix to try: scale the bridge weight down when the query names an
   ID and is short.
5. _More from E3 (contradictions missed, over-abstaining, chunk boundaries) after the full run._

## 5. What would improve the system

- A cross-encoder re-ranker on the top 30 (e.g. `bge-reranker-base`) before our boosts.
- Query rewriting / decomposition before the first search for long multi-part questions (M1).
- Better entity extraction (NER instead of capitalization heuristics) and coreference.
- A verification pass that checks each claim against its cited chunk.

## 6. Ranker weight sweep

10 questions (S2, S7, M1, M2, M3, M7, X1, X4, HB1, HC1), strategy B, `w_rrf = 1.0`, dev index:

| w_bridge \ w_query | 0.0 | 0.1 | 0.2 | 0.4 |
|---|---|---|---|---|
| 0.0 | 0.720 | 0.670 | 0.670 | 0.653 |
| 0.15 | 0.720 | 0.720 | 0.670 | 0.670 |
| 0.3 | 0.658 | 0.675 | **0.725** | 0.675 |
| 0.5 | 0.590 | 0.595 | 0.595 | 0.620 |

(MRR; recall@10 is 0.76 for `w_bridge` ≤ 0.15 and 0.78 above.) The defaults 0.3 / 0.2 have the best MRR
and the higher recall@10. This sample is small; re-run on the full index before treating it as final.
