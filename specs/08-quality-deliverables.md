# 08 — Quality and deliverables

## Automated tests (`tests/`, pytest, no network)

Fakes: `FakeStore` (in-memory dicts with cosine search), `FakeEmbedder` (deterministic hash-based
vectors), `FakeLLM` (scripted replies, can raise 429 / timeout).

| Area | Tests |
|---|---|
| normalize | whitespace/unicode normalization; hash ignores case and whitespace |
| parsers | small fixture PDF / DOCX / HTML / MD → title, headings as `#`, date, doc_type; unsupported extension raises |
| chunking | A: sizes and overlap, last chunk; B: never cuts a sentence, heading prefix, long paragraph split |
| pipeline | add → chunks for A and B; same content again → duplicate; same filename without replace → 409; replace → version 2 and old chunks gone; delete protected corpus doc → 403 |
| ranker | RRF math on a hand-made example; bridge boost lifts a connecting chunk; query-match title bonus; diversity cap; each `mode` |
| provider | retry then succeed; 429 on primary → fallback; all fail → `LLMUnavailable`; cache hit makes no call |
| citations | invented chunk_id dropped; claim without citations dropped; empty → insufficient; conflicts → conflicting |
| agent | scripted tool calls produce a trace; no tool calls → safety-net search; invalid JSON → repair → abstain |
| api | `/investigate` with fakes returns the contract; upload without token → 401; LLM down → 503 |
| metrics | Recall@K, MRR, correctness rules on tiny examples |

Command: `uv run pytest -q`. Optional: GitHub Action running pytest on push.

## Code quality rules

- Modules follow 01's layout; one job per module; no circular imports.
- Type hints on public functions; dataclasses for data passed between layers.
- No bare `except:`; external-call failures become typed errors (`LLMUnavailable`, `DocumentExists`, …)
  and map to HTTP codes in one place (API exception handlers).
- Logging: one structured line per `/investigate` (question hash, status, steps, calls, tokens, latency)
  and per ingest (doc_id, chunks, duration).

## README.md outline

1. What it is (2–3 sentences) + live demo link + screenshot.
2. Architecture diagram and the request flow (`/investigate` step by step).
3. Design decisions with reasons: Qdrant, local embeddings, hybrid + our ranker (explain the formula),
   chunking A vs B, agent loop and tools, citation validation, why no LangChain.
4. Dataset: HotpotQA subset (counts: raw, unique, sampled, seed) + synthetic incident corpus and why.
5. Run locally / ingest / test commands.
6. Deployment architecture, free-tier limits, cost estimate.
7. Evaluation summary (headline numbers) → link to EVALUATION.md.
8. Known limitations and next steps (the out-of-scope list from 01).

## AI_USAGE.md outline

- Tools used (Claude Code for specs, Cursor for implementation, …) and for what.
- What was generated vs written or changed by hand. Be specific: e.g. the ranker formula, the eval question set.
- Mistakes the AI made that you caught and fixed.
- What you verified yourself, and how.

## Submission checklist

- [ ] Public GitHub repo with incremental commit history
- [ ] Live demo URL works (after the cold start)
- [ ] ≥50,000 records indexed; counts in README
- [ ] PDF, DOCX, HTML, MD ingest works through the UI
- [ ] Upload, replace (version 2), duplicate detection and delete demonstrated
- [ ] Canonical March question answered with citations; a contradiction question shows conflicts; an unanswerable question abstains
- [ ] EVALUATION.md with ≥40 questions, ≥2 configs, failure analysis
- [ ] README and AI_USAGE.md
- [ ] No secrets in git history
- [ ] You can explain: the pipeline step by step, the ranker formula, the citation validator, the abstain path
