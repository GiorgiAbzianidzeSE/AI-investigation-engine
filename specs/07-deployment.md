# 07 — Deployment

## Topology

```
Browser ──HTTPS──► Hugging Face Space (Docker, free CPU)   ──► Qdrant Cloud free cluster (persistent)
                   FastAPI + UI + local embedding models   ──► Gemini API (primary) / Groq API (fallback)
Mac (once) ──────► scripts/ingest_all.py ─────────────────────► Qdrant Cloud
```

All persistent data lives in Qdrant Cloud, so the Space can sleep, restart or rebuild without losing
documents. The Space disk is treated as temporary.

## Account setup

1. **GitHub**: create a public repo `ai-investigation-engine`; push from the start (history is graded).
2. **Google AI Studio** (aistudio.google.com): "Get API key" → `GEMINI_API_KEY`. Pick a current Flash
   model for `GEMINI_MODEL` and note its free-tier limits (requests/min, requests/day).
3. **Groq** (console.groq.com): API key → `GROQ_API_KEY`; choose a tool-calling model (e.g. openai/gpt-oss-120b) → `GROQ_MODEL`.
4. **Qdrant Cloud** (cloud.qdrant.io): create a free cluster (1 GB) → copy the cluster URL (`QDRANT_URL`,
   including `:6333`) and create an API key (`QDRANT_API_KEY`).
5. **Hugging Face**: create a Space → SDK **Docker** → hardware "CPU basic (free)". Add the secrets
   `QDRANT_URL, QDRANT_API_KEY, GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, ADMIN_TOKEN`.
   Create a write token (`HF_TOKEN`) only to push code.
6. Make up `ADMIN_TOKEN` (a long random string, e.g. `openssl rand -hex 16`).

## Local run and offline ingest (Mac)

The development VM is too small (≈700 MB RAM) to embed 50k records. Indexing runs on the Mac.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # once
cd ai-investigation-engine
cp .env.example .env                                  # fill in the keys
uv sync --all-groups
uv run python -m scripts.make_incidents               # writes data/incidents/*
uv run python -m scripts.build_hotpot                 # downloads parquet, writes data/raw + data/hotpot_questions.jsonl
uv run python -m scripts.ingest_all                   # creates collections, ingests everything into Qdrant Cloud
uv run uvicorn app.api.main:app --reload --port 8000  # local app at http://localhost:8000
```

Expected: about 60k records embedded on CPU in minutes, plus upload time to Qdrant Cloud.
`ingest_all` is resumable.

## Docker image (Space)

- Base `python:3.11-slim`; install with `uv` from `pyproject.toml` (no dev groups).
- **Pre-download the fastembed models at build time** into `/app/models`, so a cold start doesn't download them.
- Run as a non-root user (HF requirement); listen on **port 7860** (`uvicorn app.api.main:app --host 0.0.0.0 --port 7860`).
- The Space README front-matter needs `sdk: docker` and `app_port: 7860`.
- Deploy: add the Space as a second git remote and `git push space main`
  (or let a GitHub Action mirror the repo; *optional*).

## Secrets

- Only env vars / Space secrets. `.env` is git-ignored; `.env.example` lists the names with empty values.
- The admin token protects write endpoints; questions are public.
- Before pushing: `git grep -nE "(sk-|AIza|gsk_)"` returns nothing.

## Free-tier limits to document in README

| Resource | Limit (check at signup) | Effect | Mitigation |
|---|---|---|---|
| HF Space CPU basic | sleeps after inactivity; 2 vCPU / 16 GB | first request after sleep takes ~1 min | note in README; `/health` warms it up |
| Qdrant Cloud free | 1 GB RAM, single node; may pause when idle | ~60k × 384-d vectors + payload fits | on-disk payload; resume from the console if paused |
| Gemini free tier | requests per minute/day | eval or demo can hit 429 | retries, Groq fallback, LLM cache |
| Groq free tier | requests and tokens per minute/day | same | same |

Cost: $0 on free tiers. README also gives an estimate at paid prices (tokens per question × list price)
from the usage logs.
