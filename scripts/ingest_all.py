"""Offline ingest of the whole corpus into Qdrant (run on the Mac, not on the Space).

    uv run python -m scripts.ingest_all [--skip-hotpot] [--limit N] [--batch 256]

1. creates collections + payload indexes if missing
2. ingests data/incidents/* through the normal pipeline (source = "incidents")
3. bulk-ingests HotpotQA records in batches, skipping doc_ids already present (resumable)
4. prints totals
"""
import argparse
import json
import logging
import time
from pathlib import Path

from app.config import get_settings
from app.ingest.pipeline import DocumentExists, IngestPipeline
from app.search.embedder import Embedder
from app.search.store import QdrantStore

INCIDENTS = Path("data/incidents")
RECORDS = Path("data/raw/hotpot_records.jsonl")


def ingest_incidents(pipe: IngestPipeline) -> dict:
    counts = {"added": 0, "updated": 0, "duplicate": 0, "exists": 0}
    for path in sorted(p for p in INCIDENTS.iterdir() if p.is_file() and not p.name.startswith(".")):
        try:
            r = pipe.add_file(path.name, path.read_bytes(), source="incidents")
            counts[r.status] += 1
            print(f"  {r.status:9} {r.doc_id} ({r.chunks} chunks)")
        except DocumentExists as e:
            counts["exists"] += 1
            print(f"  exists    {e.doc_id}")
    return counts


def ingest_hotpot(pipe: IngestPipeline, batch: int, limit: int | None) -> tuple[int, int]:
    added = seen = 0
    t0 = time.time()
    buf: list[dict] = []
    with RECORDS.open() as f:
        for line in f:
            buf.append(json.loads(line))
            seen += 1
            if len(buf) == batch or (limit and seen >= limit):
                added += pipe.add_records(buf)
                buf = []
                rate = seen / max(time.time() - t0, 1e-6)
                print(f"\r  hotpot: {seen} read, {added} added ({rate:.0f} rec/s)", end="", flush=True)
            if limit and seen >= limit:
                break
    if buf:
        added += pipe.add_records(buf)
    print(f"\r  hotpot: {seen} read, {added} added, {seen - added} already present")
    return seen, added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-hotpot", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="only the first N HotpotQA records")
    ap.add_argument("--batch", type=int, default=512)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    s = get_settings()
    t0 = time.time()
    store = QdrantStore(s)
    store.ensure_collections()
    pipe = IngestPipeline(store, Embedder(s), s)

    print("incidents:")
    inc = ingest_incidents(pipe)
    if not args.skip_hotpot:
        if not RECORDS.exists():
            raise SystemExit(f"{RECORDS} missing: run `uv run python -m scripts.build_hotpot` first")
        ingest_hotpot(pipe, args.batch, args.limit)

    per_strategy = {st: store.count_chunks(st) for st in ("a", "b", "na")}
    print(f"\ndocuments: {store.count_documents()}  chunks: {per_strategy}  "
          f"incident files: {inc}  elapsed: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
