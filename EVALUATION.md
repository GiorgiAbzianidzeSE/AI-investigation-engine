# Evaluation

> **Status:** final. All results are on the **full index** in Qdrant Cloud: 16 incident documents (in two
> chunking strategies) + 65,000 HotpotQA paragraphs (67k chunks). Raw per-question rows are in `eval/results/`.

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

### E1: retrieval method (full index, chunking B, 36 questions with gold documents)

| config | recall@5 | recall@10 | MRR | MRR simple | MRR multi_doc | MRR multi_hop | MRR contradictory |
|---|---|---|---|---|---|---|---|
| dense | 0.743 | 0.896 | 0.903 | 0.771 | 0.917 | 0.929 | 1.000 |
| BM25 | 0.825 | **0.950** | 0.878 | 0.938 | 0.838 | 0.869 | 0.875 |
| RRF | 0.829 | 0.947 | 0.898 | 0.938 | 0.812 | 0.964 | 0.806 |
| **full (ours)** | **0.862** | 0.947 | **0.913** | 0.854 | 0.817 | **1.000** | 0.917 |

Our ranker (min-max RRF + IDF-weighted cross-document entity bridge + query entity match, max 3 chunks per
document) is best overall on recall@5 and MRR, and finds a gold paragraph first on every multi-hop question:
the bridge term rewards paragraphs that share rare entities with other retrieved paragraphs, which is exactly
the HotpotQA bridge structure. Plain BM25 stays best on simple ID lookups (see failure analysis 4).

### E2: chunking (full index, full ranker, 22 incident questions)

| strategy | recall@5 | recall@10 | MRR |
|---|---|---|---|
| A, fixed 200-word windows | 0.821 | 0.967 | 0.747 |
| **B, structure-aware** | **0.911** | **0.982** | **0.858** |

B's chunks follow headings and carry a `title > heading:` prefix, so the right section of the right document
ranks first more often (MRR +0.11, recall@5 +0.09), most of all on simple lookups (MRR 0.85 vs 0.58).

### E3: end to end

Full index (65k HotpotQA paragraphs + incident corpus), strategy B, full ranker, all 42 questions
(`uv run python -m eval.run_eval --experiments e3`, raw rows in `eval/results/e3-b-full.json`).

| type | n | correct (strict) | content correct | citation precision | citation support | latency (s) | LLM calls | tokens |
|---|---|---|---|---|---|---|---|---|
| **all** | 42 | **0.786** | 0.833 | 0.845 | 0.971 | 37.4 | 4.2 | 11.7k |
| simple | 8 | 0.875 | 0.875 | 0.633 | 1.0 | * | 3.3 | 5.5k |
| multi_doc | 8 | 0.625 | 0.750 | 0.861 | 1.0 | 20.6 | 4.0 | 9.8k |
| multi_hop (HotpotQA) | 14 | 0.857 | 0.857 | 0.964 | 1.0 | 61.8 | 4.0 | 11.7k |
| unanswerable | 6 | **1.0** | - | - | - | 51.7 | 6.5 | 24.7k |
| contradictory | 6 | 0.5 | - | 0.833 | 0.833 | 38.3 | 4.2 | 9.9k |

*Strict* follows the spec (status must be `answered` and every `must_include` present); *content correct*
ignores the status, to separate wrong answers from right answers that also flagged a conflict or abstained.
\* Simple questions were served from the LLM cache on the final run (an interrupted run had already answered
them), so their latency is not meaningful.

**Models.** The Gemini free tier allows 20 requests/day per model, so the run went down the model chain: 35 of
the 42 questions were answered by `gemini-3.5-flash-lite`, 8 calls by `gemini-3-flash-preview`, a few by
`gemini-3.5-flash` / Groq `gpt-oss-120b` (per-question `providers` are in the rows). The numbers are therefore
mostly a flash-lite result; a stronger model would likely help the contradiction cases below.

## 3. Cost and latency

- **Per question:** 4.2 LLM calls, about 11.7k tokens (mostly input: tool results and the evidence block),
  37 s on average. Unanswerable questions cost the most (6.5 calls, 24.7k tokens): the agent keeps searching
  before it gives up, which is the desired behavior but the most expensive one.
- **Cost:** 0 on the free tiers used. At paid list prices for a flash-lite class model (about $0.10 per million
  input tokens, $0.40 per million output) a question costs roughly $0.0015, the whole 42-question run about
  $0.06; a flash class model is a few times more.
- **Latency** is dominated by LLM round trips (each 3-15 s on the free tier, plus 429 retries); retrieval is
  ~0.1-0.3 s per search against Qdrant Cloud, and query embeddings are LRU-cached.
- **Caching:** identical LLM requests are served from a JSON cache, so re-running the eval after a grader change
  costs no API calls (`--experiments rescore`).

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
5. **Contradictions missed (E3: X1, X2, X6).** The agent answered confidently from the internal incident report
   and postmortem and never retrieved the other side (the public status page blaming a card network, a
   different end time in the finance summary). Both sides are needed in the evidence for the synthesis step to
   see a conflict, and the agent stops searching once one consistent story is found. X3-X5, where both sides
   share the query's words, were caught. Fix: a dedicated "look for disagreement" search before finishing
   (e.g. query the same entity restricted to other `doc_type`s), and a stronger model for synthesis.
6. **Over-abstaining despite a correct answer (M2, M4).** The answer text is right (CHG-0327 vs the
   reconciliation job's lock; CHG-0331 reverting the pool change) but the status is `insufficient_evidence`:
   the model marked part of the question as missing (e.g. *which incident* led to the revert) although the
   evidence contained it. Fix: have the validator downgrade only when no claim survives, and ask the model to
   list missing items explicitly so that partial answers stay `answered`.
7. **A real conflict next to a complete answer (M1).** The brief's March question returned
   `conflicting_evidence`: every change and service is named, but the status page's "third-party card network"
   explanation conflicts with the incident report. Strictly wrong by the spec, arguably the most honest answer.
8. **Incomplete answers (S5).** "CHG-0331 restored the pool" without the size (200). The evidence had it;
   flash-lite summarized too much. A claim-completeness check (does the answer cover each part of the
   question) would catch it.
9. **Grader too strict (HB3, HC4).** HotpotQA gold answers are full names ("Edith Louisa Cavell",
   "Timothy Simon \"Tim\" Roth"); the answers say "Edith Cavell" / "Tim Roth", which are correct. Strict
   containment counts them wrong, so multi_hop is understated by 2/14. Token-F1 or alias lists would fix it.
10. **Citation precision on simple questions is low (0.63)** although support is 1.0: the agent adds extra
    citations to related documents (the changelog, the ops review) next to the gold one. Not wrong, but noisy.

## 5. What would improve the system

- A cross-encoder re-ranker on the top 30 (e.g. `bge-reranker-base`) before our boosts.
- Query rewriting / decomposition before the first search for long multi-part questions (M1).
- Better entity extraction (NER instead of capitalization heuristics) and coreference.
- A verification pass that checks each claim against its cited chunk.

## 6. Ranker weight sweep

10 questions (S2, S7, M1, M2, M3, M7, X1, X4, HB1, HC1), strategy B, `w_rrf = 1.0`, full index (MRR;
recall@10 is 0.96 everywhere):

| w_bridge \ w_query | 0.0 | 0.1 | 0.2 | 0.4 |
|---|---|---|---|---|
| 0.0 | 0.917 | 0.867 | 0.867 | 0.850 |
| 0.15 | 0.917 | 0.917 | 0.867 | 0.867 |
| 0.3 | **0.920** | **0.920** | **0.920** | 0.870 |
| 0.5 | 0.870 | 0.920 | 0.870 | 0.870 |

`w_bridge = 0.3` is the best row for every `w_query` ≤ 0.2, so the defaults (0.3 / 0.2) sit on the plateau.
Recall@5 is highest at 0.3 / 0.4 (0.837 vs 0.803), at a small MRR cost. The sample is small (10 questions):
differences of 0.05 MRR are one question moving one rank.
