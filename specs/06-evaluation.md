# 06 — Evaluation

## Question set (`eval/questions.jsonl`), 42 questions

One JSON object per line:

```json
{"id": "M1", "type": "multi_doc", "corpus": "incidents", "question": "...",
 "must_include": ["CHG-0314", "payments-gateway"], "gold_docs": ["incidents:inc-2041-incident-report-pdf"],
 "expect_status": "answered"}
```

| Type | Count | Source |
|---|---|---|
| simple | 8 | incidents (Appendix B) |
| multi_doc | 8 | incidents (Appendix B), including the brief's March question |
| multi_hop | 14 | HotpotQA: seeded sample (seed 42) from `data/hotpot_questions.jsonl`, 7 bridge + 7 comparison, only questions whose paragraphs are indexed |
| unanswerable | 6 | incidents (Appendix B) |
| contradictory | 6 | incidents (Appendix B) |

`expect_status`: `answered` for simple / multi_doc / multi_hop; `insufficient_evidence` for unanswerable;
`conflicting_evidence` for contradictory. HotpotQA `must_include` = `[gold answer]` (for yes/no questions: `["yes"]` / `["no"]`).

## Metrics (`eval/metrics.py`)

Document-level, using `gold_docs`:

- **Recall@K** (K = 5, 10): share of gold documents found among the top-K retrieved *documents*
  (chunks collapsed to their `doc_id`, first occurrence keeps the rank).
- **MRR**: mean of 1 / rank of the first gold document (0 if absent in the top 10).
- **Answer Correctness**:
  - Answerable questions: correct when the status is `answered` and every `must_include` string appears
    (case-insensitive, punctuation-normalized) in the answer + claims. Also report token-F1 against the
    joined `must_include` as a softer score.
  - Unanswerable: correct when the status is `insufficient_evidence`.
  - Contradictory: correct when the status is `conflicting_evidence` (or `conflicts` is non-empty) **and**
    the conflict's citations cover both sides' gold documents (partial credit if only the status is right).
- **Citation Accuracy**:
  - *Precision*: share of cited chunks whose `doc_id` is in `gold_docs`.
  - *Support*: share of answered questions with ≥1 correct citation.
- Also logged per question: latency, LLM calls, tokens, number of agent steps, dropped citations.

Retrieval metrics skip unanswerable questions (no gold documents).

## Configurations compared (≥2 required)

| Experiment | Configs | Needs LLM? |
|---|---|---|
| E1 Retrieval method | `dense` vs `sparse` vs `rrf` vs `full` (our ranker), strategy B | no |
| E2 Chunking | strategy A vs B, mode `full`, incident questions only | no (retrieval) + optional end-to-end |
| E3 End to end | strategy B + `full` (+ optional A + `full`) through `/investigate` logic | yes |

E1 and E2 run on the question text directly through `HybridSearcher.search` (single-shot retrieval), so
they are cheap and deterministic. E3 runs the full agent with `LLM_CACHE_PATH=eval/results/llm.cache.json`.

## Runner (`eval/run_eval.py`)

```
uv run python -m eval.run_eval --experiments e1,e2        # retrieval only, fast
uv run python -m eval.run_eval --experiments e3 [--limit N]
```

- Writes `eval/results/<experiment>-<config>.json` (per-question rows + aggregates) and prints a markdown table.
- Resumable: skips questions already in the results file.
- Sleeps / backs off on rate limits (the provider already retries); uses Groq if Gemini runs out.

## EVALUATION.md (deliverable)

1. Method: dataset, question types, how gold labels were made, metric definitions.
2. Results tables: E1, E2, E3, overall and per question type.
3. Cost and latency: average tokens, calls and seconds per question; estimated cost at paid prices.
4. **Failure analysis**: at least 5 concrete failed questions. For each: what happened, why
   (retrieval miss, ranking, chunk boundary, model ignored a conflict, over-abstaining…), and the fix you would try.
5. What would improve the system (re-ranker, better entity extraction, query rewriting, bigger model…).
6. Ranker weight sweep notes (03).
