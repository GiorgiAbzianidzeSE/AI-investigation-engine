---
title: AI Investigation Engine
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# AI Investigation Engine

Answers questions **by investigating** a document collection: the model breaks a question into steps,
searches several sources with tools, links facts across documents, and answers **only with cited evidence**.
When the evidence is missing it says so; when sources disagree it shows both sides. This is agentic RAG over
hybrid search, with our own ranking function, not "chat with a PDF".

- **Live demo:** _(Render URL, added after deployment)_
- **Evaluation:** [EVALUATION.md](EVALUATION.md) · **AI usage:** [AI_USAGE.md](AI_USAGE.md) · **Specs:** [specs/](specs/README.md)

Try: *"Which system changes caused payment-processing delays in March 2026, which services were affected, and
which documents prove it?"*

## Architecture

```
          ┌──────────────── offline, run once on a laptop ────────────────┐
HotpotQA ─┤ scripts/build_hotpot.py ──┐                                   │
incidents ┤ scripts/make_incidents.py ┴─► ingest pipeline ────────────────┼──► Qdrant Cloud
          └────────────────────────────────────────────────────────────────┘     chunks (dense + BM25)
                                                                                 documents (registry)
Browser ──► FastAPI in a Docker container (Render)
            ├─ /documents   list · upload · replace · delete ─► ingest pipeline
            ├─ /investigate question ─► agent loop ─► Gemini (fallback: Groq)
            └─ /            single-page UI
```

### What happens on `/investigate`

1. **Tool phase** (`app/investigate/agent.py`): the model gets the question and three tools: `search_corpus(query,
   doc_ids?)`, `get_document(doc_id)` and `finish(reason)`. The system prompt tells it to split the question into
   sub-questions, search once per sub-question, follow newly discovered entities (change IDs, services, people),
   and look for sources that might disagree. At most 6 rounds.
2. Every chunk any tool returns goes into the run's **evidence set**. If the model searched nothing, we run one
   search with the question ourselves (safety net).
3. **Synthesis**: a separate call gets only the numbered evidence list (up to 24 chunks, most-retrieved first)
   and must return JSON: `status`, `answer`, `claims[{text, citations}]`, `conflicts[{topic, positions}]`,
   `missing`. Invalid JSON gets one repair retry, then the system abstains (`invalid_model_output`).
4. **Citation validator** (`app/investigate/citations.py`), enforced in code: citations that aren't in the evidence
   set are dropped; claims left without citations are dropped; a conflict needs two cited positions;
   `answered` with no claims becomes `insufficient_evidence`; remaining conflicts force `conflicting_evidence`.
   `sources` are only the chunks actually cited. The number of dropped citations is returned.
5. The response carries the trace (each tool call), usage (LLM calls, cache hits, tokens, provider, latency), and
   the config. One log line per request.

## Design decisions

| Decision | Why |
|---|---|
| **Qdrant Cloud** | Dense and sparse vectors in one collection; data lives outside the app, so the free Space can sleep or rebuild without losing anything. |
| **Local embeddings** (`fastembed`: `bge-small-en-v1.5`, 384-d, plus `Qdrant/bm25`) | Free, no rate limits, the same model at index and query time. Baked into the Docker image. |
| **Hybrid search, fused by our ranker** | Dense and BM25 run as *separate* queries (50 candidates each); fusion is our code, not Qdrant's built-in fusion. |
| **Two chunking strategies** | A: 200-word windows with 40 overlap. B: split at headings and paragraphs, never cut a sentence, prefix `title > heading:`. Both are indexed and compared in the eval. |
| **Agent loop with tool calling** | Multi-hop questions need a second search for an entity the first search revealed. |
| **Validation in code** | The model is never trusted to cite correctly; anything it can't back with a retrieved chunk is removed. |
| **No LangChain / LlamaIndex** | Every step is a small plain-Python module you can read and change. Only `search/store.py` imports `qdrant_client` and only `llm/provider.py` imports `openai`, so tests swap in fakes. |
| **Gemini + Groq via the `openai` SDK** | One code path for both OpenAI-compatible endpoints. `GEMINI_MODEL` / `GROQ_MODEL` take comma-separated model chains (free-tier quotas are per model; gemini-3.5-flash allows only 20 requests/day). 45 s timeout, retry on 429/5xx/timeout (2 s, 4 s), a model whose *daily* quota is spent is skipped for an hour, then the next model; all down → HTTP 503, never an invented answer. Gemini 3 thought signatures are echoed back to the model that produced them; another Gemini model gets Google's placeholder signature after a mid-investigation fallback. Responses are cached (memory, and a JSON file for the eval). |

### The ranker (`app/search/ranker.py`)

```
score(c) = 1.0 · RRF_minmax(c) + 0.3 · bridge(c) + 0.2 · query_match(c)      then max 3 chunks per document
```

- **RRF**: `Σ_lists 1 / (60 + rank)` over the dense and BM25 lists, min-max scaled over the top-30 pool.
  Rank-based, so cosine and BM25 scores are never mixed.
- **bridge** (the multi-hop signal): the chunk's entities (IDs like `CHG-0314`, kebab-case service names, dates,
  capitalized phrases, the title) that also appear in candidates from *other* documents, each weighted by rarity
  `log(1 + N_docs / df)`. A chunk that links two documents (an incident report that cites a change ID, two
  Wikipedia paragraphs naming the same person) moves up. IDs that every summary page repeats count little.
- **query_match**: the query's entities found in the chunk; 1 point for the body, 2 for the title, out of 2
  per entity. A chunk *about* `CHG-0314` beats one that only mentions it.
- **diversity**: at most 3 chunks per document in the final top-K.

Entity extraction is regex-based on purpose: cheap, deterministic, explainable, no extra LLM call.

*How the weights were chosen:* the first version (spec defaults, RRF divided by its max, unweighted bridge) scored
**below** plain RRF (MRR 0.39 vs 0.51). The cause: with k = 60, RRF divided by its max is compressed (rank 10 is
still ≈ 0.87), so the boosts swamped relevance, and hub documents that mention every ID won the bridge term for
every query. After min-max scaling, rarity weighting and a real title bonus, a 4 × 4 grid over `w_bridge`
× `w_query` on 10 eval questions picked 0.3 / 0.2 (details in [EVALUATION.md](EVALUATION.md)).

## Data

| Corpus | What | Size |
|---|---|---|
| HotpotQA (distractor, validation) | Wikipedia paragraphs; 7,405 questions × 10 paragraphs = 73,700 raw, **66,635 unique** (dedup by `sha1(title + text)`); seeded sample (seed 42) of 7,210 questions keeps **65,000 paragraphs**, all paragraphs of each kept question | 65,000 records, one chunk each |
| Synthetic "Northwind Payments" incidents | 16 documents in PDF / DOCX / HTML / Markdown: changelog, 5 change requests, 3 incident reports, a postmortem, status page, finance summary, service catalog, runbook, architecture doc, ops review. 5 planted contradictions and 6 deliberate gaps ([specs/appendix-a](specs/appendix-a-incident-corpus.md)) | 16 documents; 32 chunks (A), 86 chunks (B) |

HotpotQA gives scale and real multi-hop questions. The incident corpus gives the brief's investigation scenario
(changes → incidents → affected services), several file formats, contradictions and unanswerable questions. Its
text lives in `scripts/incident_texts.py`, so it's reviewable and reproducible.

**Ingestion** (`app/ingest/`): parse (PDF headings are detected from bold or larger fonts; DOCX/HTML tables
are kept as one line per row) → normalize (NFKC, whitespace) → exact-duplicate check on the content hash →
chunk A and B → embed → near-duplicate check (cosine ≥ 0.97 against another document's chunk → flagged, still
indexed) → upsert. The same filename with `replace=true` → old chunks deleted, `version + 1`. Only uploaded
documents can be deleted through the API.

## Run locally

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # once
cp .env.example .env                                       # fill in keys (see below)
uv sync --all-groups
uv run python -m scripts.make_incidents                    # data/incidents/* (already committed)
uv run python -m scripts.build_hotpot                      # downloads HotpotQA, writes data/raw + data/hotpot_questions.jsonl
uv run python -m scripts.ingest_all                        # collections + incidents + 65k records (resumable, ~20 min on a laptop CPU)
uv run uvicorn app.api.main:app --reload --port 8000       # http://localhost:8000
uv run pytest -q                                           # 72 tests, no network
```

Without a Qdrant server you can develop against embedded Qdrant: `QDRANT_PATH=data/cache/qdrant-dev`
(use `--limit 2000` for a quick partial ingest).

Evaluation: `uv run python -m eval.run_eval --experiments e1,e2,sweep` (retrieval, no LLM) and
`--experiments e3` (end to end; LLM responses cached in `eval/results/llm.cache.json`).

## Deployment

- **Render free web service** runs the Docker image (FastAPI, the UI and the local embedding models baked into
  the image, non-root user, listens on `$PORT`). `render.yaml` is a blueprint: New → Blueprint → this repo, then
  fill in the secret env vars. Hugging Face Docker Spaces were the first choice, but free CPU basic for Docker
  Spaces now requires a PRO subscription; the same image still runs there (port 7860,
  `HF_TOKEN=hf_... scripts/push_space.sh <user>/<space>`).
- **Qdrant Cloud** free cluster holds all data, so the container disk is treated as temporary.
- **Secrets** are Space secrets / `.env` only (git-ignored): `QDRANT_URL, QDRANT_API_KEY, GEMINI_API_KEY,
  GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, ADMIN_TOKEN`. Asking questions is public; upload, replace and delete
  need the `X-Admin-Token` header (compared with `hmac.compare_digest`). Writes are disabled while
  `ADMIN_TOKEN` is unset.

### Free-tier limits

| Resource | Limit | Effect | Mitigation |
|---|---|---|---|
| Render free web service | 512 MB RAM, 0.1 CPU; sleeps after 15 min idle | cold start ~1 min; slower embedding of queries | open `/health` first to wake it; app idles at ~350 MB |
| Qdrant Cloud free | 1 GB RAM, single node; pauses when idle for long | 65k × 384-d vectors + payload fit | payload on disk; resume from the console if paused |
| Gemini free tier | requests per minute / per day (20/day on gemini-3.5-flash) | the eval or the demo can hit 429 | model chain, daily-quota cooldown, Groq fallback, LLM cache |
| Groq free tier | requests and tokens per minute / per day | same | same |

**Cost:** $0 on free tiers. At paid prices, see the per-question token averages in [EVALUATION.md](EVALUATION.md).

## Known limitations and next steps

- No streaming; an investigation takes 10–60 s.
- Contradiction detection depends on the model comparing evidence; misses are listed in EVALUATION.md.
- Entity extraction is regex-based: no coreference ("the incident" ≠ "INC-2041"), English only.
- Next: a cross-encoder re-ranker, query rewriting, multi-agent verification, load testing, a prompt-injection
  test suite, user accounts, a nicer UI.
