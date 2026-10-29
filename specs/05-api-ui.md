# 05 — API and UI

## API (`api/main.py`, FastAPI)

Services (store, embedder, searcher, pipeline, LLM provider, agent) are built once at startup and
reached through FastAPI dependencies, so tests can override them with fakes.

| Method | Path | Body / params | Response |
|---|---|---|---|
| GET | `/health` | — | `{qdrant: ok/error, documents: n, llm_providers: [...], embed_cache: {...}}` |
| GET | `/documents` | `source?`, `q?` (title search), `limit=50`, `offset?` | `{items: [doc metadata], next_offset}` |
| GET | `/documents/{doc_id}` | `strategy=b` | `{document, chunks: [{chunk_id, heading, text}]}` |
| POST | `/documents` | multipart `file`, `replace=false`; header `X-Admin-Token` only when `replace=true` | `IngestResult {status, doc_id, chunks, version, duplicate_of, near_duplicate_of}` |
| DELETE | `/documents/{doc_id}` | header `X-Admin-Token` | `{deleted: doc_id}` |
| POST | `/investigate` | `{question, strategy?: "a"/"b", mode?: "dense"/"sparse"/"rrf"/"full"}` | response contract from 04 |
| GET | `/` | — | the UI |

Error mapping:

| Situation | Status |
|---|---|
| Missing or wrong admin token | 401 |
| Deleting a non-upload document | 403 |
| Unknown document | 404 |
| Already exists without `replace` | 409 |
| Unsupported file type | 415 |
| Empty or unparseable file; question empty or over 500 chars | 422 |
| LLM unavailable | 503 |
| Qdrant unreachable | 503 |

All errors use the body `{"error": code, "detail": text}`.

Limits: upload ≤ 10 MB. Admin token compared with `hmac.compare_digest`.

## UI (`api/static/index.html`)

One HTML file, vanilla JS + a little CSS, served at `/`. Two tabs.

**Investigate tab**
- Question textarea, a strategy/mode selector (advanced, collapsed), and an "Investigate" button with a loading state.
- 4–5 example question chips (the canonical March question, one contradiction, one unanswerable, one HotpotQA multi-hop).
- Result:
  - Status badge: Answered (green), Conflicting evidence (amber), Insufficient evidence (grey).
  - Answer text, then the claims list. Each claim has citation chips `[1] [2]`.
  - Clicking a chip highlights the source card.
  - Conflicts box listing each position with its citations.
  - "Missing" list when the system abstains.
  - Sources panel: title, doc_id, date, snippet, and a link to open the full document (`GET /documents/{id}`).
  - Collapsible trace (step, tool, args, result count) and usage (calls, tokens, latency, provider).
- Errors (503 etc.) shown as a readable message, never a blank screen.

**Documents tab**
- Search box (title) + source filter (all / incidents / upload / hotpotqa) + paginated list:
  title, format, type, date, version, near-duplicate flag.
- Admin token field (kept in `sessionStorage`).
- Upload (file + "replace existing" checkbox). The result message shows added / updated / duplicate / near-duplicate.
- Delete button on uploaded documents only.
- Document viewer: metadata + chunks for strategy A or B (switchable). Shows the chunking difference.
