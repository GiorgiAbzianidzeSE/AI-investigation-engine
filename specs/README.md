# AI Investigation Engine — Specs

Implementation specs for the Upgaming *Applied AI – AI Investigation Engine* task.
Written to be built with Cursor; each file is self-contained for its area.

| File | Covers |
|---|---|
| [01-overview.md](01-overview.md) | Goal, scope, accounts, stack, architecture, repo layout, conventions |
| [02-ingestion.md](02-ingestion.md) | File formats, parsing, metadata, chunking A/B, dedup, add/update/delete, corpus build |
| [03-retrieval.md](03-retrieval.md) | Embeddings, Qdrant layout, hybrid search, the custom ranker |
| [04-investigation.md](04-investigation.md) | LLM provider, agent loop + tools, citations, contradictions, abstention, caching |
| [05-api-ui.md](05-api-ui.md) | REST API and the single-page UI |
| [06-evaluation.md](06-evaluation.md) | Question set, metrics, configurations, EVALUATION.md |
| [07-deployment.md](07-deployment.md) | Account setup, offline ingest on the Mac, Hugging Face Space, secrets, limits |
| [08-quality-deliverables.md](08-quality-deliverables.md) | Tests, error handling, logging, README / AI_USAGE outlines, submission checklist |
| [appendix-a-incident-corpus.md](appendix-a-incident-corpus.md) | The synthetic "Northwind Payments" documents: facts, contradictions, gaps |
| [appendix-b-eval-questions.md](appendix-b-eval-questions.md) | The 42 evaluation questions with gold answers and gold documents |

## Build order (one commit or more per step)

1. Skeleton: `pyproject.toml`, config, `.env.example`, pytest runs.
2. Ingestion: parsers, normalize, chunking A/B, dedup + unit tests.
3. Storage + embeddings: Qdrant store, embedder, ingest pipeline (add/update/delete) + tests with fakes.
4. Corpus: generate incident documents (Appendix A), HotpotQA subset script → run ingest on the Mac.
5. Retrieval: hybrid search + ranker + tests.
6. Investigation: LLM provider, tools, agent loop, citation validator + tests.
7. API + UI.
8. Evaluation: questions file (Appendix B + HotpotQA sample), runner, EVALUATION.md.
9. Deploy to Hugging Face Space, README, AI_USAGE.md.

**Time-box rule:** steps 1–9 are the core. Anything marked *optional* is done only after step 9 works end to end.
