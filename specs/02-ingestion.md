# 02 — Ingestion

## Supported formats

| Format | Library | Extracted |
|---|---|---|
| PDF | `pypdf` | text per page; title from PDF metadata if present |
| DOCX | `python-docx` | paragraphs; Heading/Title styles become `# heading` lines; title from core properties |
| HTML | `beautifulsoup4` | `<title>`; h1–h4 → `# heading`; p, li, td, pre; drop script/style/nav/footer |
| MD / TXT | built-in | raw text (Markdown headings already use `#`) |

Every parser returns the same structure, `ParsedDocument(title, text, format, date, doc_type)`, with
headings normalized to `# ` lines so chunking strategy B works the same way for every format.
An unknown extension raises a clear "unsupported format" error (API: 415). A file with no text gives API 422.

## Metadata

Per document (stored in the `documents` registry, see 03):

`doc_id, title, filename, source (hotpotqa | incidents | upload), format, doc_type, date, content_hash,
version, chunk_count {a, b}, near_duplicate_of, created_at, updated_at`

- `date`: first ISO date (`2026-03-05`) or long date (`March 5, 2026`) found in the text.
- `doc_type`: guessed from filename/title keywords: change_request, changelog, incident, postmortem,
  runbook, status_page, report, service_doc, wiki, document.
- `doc_id`: `"<source>:<slug(filename)>"` for files; `"hp:<sha1(title + text)[:16]>"` for HotpotQA.
  Same filename re-uploaded = same `doc_id` (this is how update works).

## Normalization

NFKC unicode, `\r\n` → `\n`, collapse spaces/tabs, trim lines, keep paragraph breaks (max one blank line).
`content_hash = sha256(lowercased, whitespace-collapsed normalized text)`.

## Chunking — two strategies (both implemented, compared in eval)

**A — fixed window:** 200 words per chunk, 40-word overlap, structure-blind.

**B — structure-aware:**
1. Split the text into sections at `# heading` lines, and into paragraphs at blank lines.
2. Keep a paragraph whole if it is ≤200 words; otherwise split it into sentences.
3. Pack paragraphs/sentences into chunks of at most ~200 words without cutting a sentence.
4. Prefix each chunk with `"<title> > <heading>: "` so it keeps its context when retrieved alone.

Chunk payload: `chunk_id = "<doc_id>#<strategy><index>"`, `doc_id, title, text, heading, index, strategy,
source, format, doc_type, date`.

File documents (incidents, uploads) are chunked and indexed **twice**, once per strategy
(`strategy = "a"` and `"b"`). HotpotQA paragraphs are short (one chunk each), so they are indexed
**once** with `strategy = "na"` (fixed-window chunker) and are visible to both strategies at query time.

## Duplicate handling

1. **Exact duplicate (document level):** before indexing, look up `content_hash` in the registry.
   If found → return `status: "duplicate", duplicate_of: <doc_id>` and index nothing.
2. **Near duplicate (file documents: uploads and incidents):** after embedding, query the 3 nearest chunks for the first 3
   chunks of the new document. If any chunk from a *different* document has cosine ≥ 0.97 → set
   `near_duplicate_of` on the document. The document is still indexed; the UI shows the flag.
3. **Bulk (HotpotQA):** the same paragraph appears under many questions → dedup by `doc_id`
   (hash of title + text) while building the corpus. Report raw vs unique counts in README.

## Add / update / delete

- **Add:** parse → normalize → hash check → chunk (A and B) → embed (dense + sparse) →
  near-dup check → upsert chunks → upsert registry entry (`version = 1`).
- **Update:** upload with `replace=true` and the same filename → delete the old chunks by
  `doc_id` → insert new chunks → registry `version += 1`, `created_at` kept, `updated_at` = now.
  Without `replace=true`, an existing `doc_id` → error 409 "already exists".
- **Delete:** delete chunks and registry entry by `doc_id` filter. Only `source = "upload"` documents can
  be deleted through the API (403 otherwise), so a demo visitor can't wipe the base corpus.

## Corpus build (offline, run on the Mac)

### HotpotQA subset (≥50,000 records)

- Source: HotpotQA, *distractor* config, *validation* split, parquet from Hugging Face:
  `https://huggingface.co/api/datasets/hotpotqa/hotpot_qa/parquet/distractor/validation` lists the file URL.
  (7,405 questions × 10 paragraphs each.)
- Each paragraph (title + sentences joined) = one record. Dedup by `doc_id`. Expected ≈ 60–70k unique.
- If the unique count is far above budget, take a **seeded** random sample of *questions* (seed 42) and
  keep all paragraphs of the sampled questions, so every sampled question stays answerable. Minimum 50,000.
- Also write `data/hotpot_questions.jsonl` (question, answer, type bridge/comparison, gold `doc_id`s from
  `supporting_facts` titles) for the evaluation sample.
- `scripts/build_hotpot.py` writes `data/raw/hotpot_records.jsonl` (git-ignored) + prints counts.

### Synthetic incident corpus

`scripts/make_incidents.py` renders the 16 documents (+3 dedup-demo files) defined in
[appendix-a-incident-corpus.md](appendix-a-incident-corpus.md) to PDF / DOCX / HTML / MD / TXT in
`data/incidents/` (committed). Text content lives in the script so it is reviewable and reproducible.
PDF generation: `fpdf2` (core fonts, so ASCII-only text); DOCX: `python-docx`.

### Ingest runner

`scripts/ingest_all.py`:
1. Creates collections and payload indexes if missing.
2. Ingests every file in `data/incidents/` through the normal pipeline (`source = "incidents"`).
3. Bulk-ingests HotpotQA records in batches of 256 (embed → upsert chunks + registry), with progress
   output, skipping `doc_id`s already present so a crashed run can resume.
4. Prints totals: documents, chunks per strategy, duplicates skipped, elapsed time.
