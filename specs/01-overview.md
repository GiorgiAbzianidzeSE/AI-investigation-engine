# 01 — Overview

## Goal

A system that answers questions **by investigating** a large document collection: it splits a question
into steps, searches several sources, links facts across documents, and answers **only with cited
evidence**. Missing evidence → it says so. Conflicting sources → it shows both sides.

It must **not** be a "chat with PDF" app. The reference question from the brief:

> Which system changes caused payment-processing delays in March, which services were affected,
> and which documents prove it?

## Scope

### Core (all required by the brief)

1. Ingest ≥3 file formats (we do PDF, DOCX, HTML, Markdown/TXT) with metadata, chunking, dedup,
   add / update / delete, and **two chunking strategies compared**.
2. Vector DB with embeddings, semantic search, **hybrid search** (semantic + keyword), and **one ranking
   algorithm written by us** (not only a library call).
3. RAG with multi-step investigation, multi-document synthesis, citations, contradiction detection,
   abstention, LLM error/limit handling, and **tool calling**.
4. Automated evaluation: ≥40 questions, Recall@K, MRR, Answer Correctness, Citation Accuracy,
   **≥2 configurations compared**, failure analysis.
5. Python backend + functional UI.
6. ≥50,000 text records from a reproducible subset.
7. Public URL on free hosting; data survives restarts; secrets protected; limits documented.
8. Deliverables: GitHub repo with real history, live demo, README, EVALUATION.md, AI_USAGE.md.

### Bonus included (small, and they protect the demo)

- Query-embedding cache + LLM response cache.
- Per-request usage logging: LLM calls, tokens, latency.
- The tool-calling loop is "agentic RAG"; README calls it that.
- Two LLM providers (Gemini primary, Groq fallback).

### Out of scope (list as "next steps" in README)

Streaming, multi-agent setup, cross-encoder re-ranker, load testing, prompt-injection test suite,
user accounts, polished UI design.

### Anti-goals (fail even if it "works")

- An answer containing a fact or a citation that is not in the retrieved chunks.
- Search ranking that is only a library default (e.g. only Qdrant's built-in fusion).
- Code too framework-heavy to explain and modify live in the interview without AI help.
  → **No LangChain / LlamaIndex.** Plain Python modules and thin SDK clients.

## Accounts and secrets (all free, no card)

| Service | Purpose | Values |
|---|---|---|
| GitHub | public repo (history is graded) | — |
| Google AI Studio | Gemini API key, primary LLM | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| Groq | fallback LLM | `GROQ_API_KEY`, `GROQ_MODEL` |
| Qdrant Cloud | free 1 GB cluster, persistent vector DB | `QDRANT_URL`, `QDRANT_API_KEY` |
| Hugging Face | Docker Space hosting the app | Space secrets; `HF_TOKEN` only for pushing |
| (self-made) | protects upload/replace/delete on the public demo | `ADMIN_TOKEN` |

Setup steps: see [07-deployment.md](07-deployment.md).

## Stack

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.11+, managed with `uv` | brief requires Python |
| API | FastAPI + uvicorn | small, typed, auto `/docs` page |
| Vector DB | Qdrant Cloud (free) | dense + sparse vectors in one place, persists outside the app |
| Dense embeddings | `BAAI/bge-small-en-v1.5` via `fastembed` (384-d, local ONNX) | free, no rate limits, same model at index and query time |
| Keyword search | BM25 sparse vectors via `fastembed` (`Qdrant/bm25`), IDF in Qdrant | real keyword search, stored next to dense vectors |
| LLM | `openai` SDK against OpenAI-compatible endpoints: Gemini (primary), Groq (fallback) | one client code path, native tool calling, free tiers |
| Parsing | `pypdf`, `python-docx`, `beautifulsoup4` | one small library per format |
| UI | one static HTML page + vanilla JS, served by FastAPI | no build step; function over design |
| Tests | `pytest` with fake store / fake embedder / fake LLM | no network in unit tests |
| Hosting | Hugging Face Docker Space (free CPU) | enough RAM for local embeddings, public URL |

## Architecture

```
          ┌────────────── offline, run once on the Mac ──────────────┐
HotpotQA ─┤ scripts/build_hotpot.py ─┐                               │
incidents ┤ scripts/make_incidents.py┴─► ingest pipeline ────────────┼──► Qdrant Cloud
          └───────────────────────────────────────────────────────────┘     • chunks
                                                                            • documents
Browser ──► FastAPI app (Hugging Face Space)
            ├─ /documents   list · upload · replace · delete ─► ingest pipeline
            ├─ /investigate question ─► agent loop
            │     plan → tool calls (search_corpus, get_document) → hybrid search → our ranker
            │     → synthesize JSON → citation validator → answered | insufficient | conflicting
            └─ /            static UI
```

## Repo layout

```
ai-investigation-engine/
  app/
    config.py              settings from env (pydantic-settings)
    ingest/  parsers.py  normalize.py  chunking.py  pipeline.py
    search/  embedder.py  store.py  hybrid.py  ranker.py
    llm/     provider.py  prompts.py
    investigate/  tools.py  agent.py  citations.py
    api/     main.py  static/index.html
  scripts/   make_incidents.py  build_hotpot.py  ingest_all.py
  eval/      questions.jsonl  run_eval.py  metrics.py  results/
  data/incidents/          generated incident files (committed, small)
  tests/
  specs/
  Dockerfile  README.md  EVALUATION.md  AI_USAGE.md  .env.example  .gitignore  pyproject.toml
```

## Conventions

- Only `search/store.py` imports `qdrant_client`; only `llm/provider.py` imports `openai`.
  Everything else receives these objects as constructor arguments, so tests can pass fakes.
- All tunables (chunk size, K, ranker weights, max agent steps, models) live in `config.py`, read from env.
- No secrets in code or git. `.env` is git-ignored; `.env.example` is committed.
- Logging via `logging`, one line per request with timings and usage.
