"""Build the HotpotQA record subset (>= 50,000 paragraphs) and the question file used by the evaluation.

    uv run python -m scripts.build_hotpot [--max-records 65000] [--seed 42]

Source: HotpotQA distractor / validation (7,405 questions x 10 paragraphs). One record per paragraph,
deduplicated by doc_id = "hp:" + sha1(title + text)[:16]. If the unique count is above --max-records, a seeded
sample of *questions* is kept together with all of their paragraphs, so every kept question stays answerable.

Writes data/raw/hotpot_records.jsonl (git-ignored) and data/hotpot_questions.jsonl.
"""
import argparse
import hashlib
import json
import random
import urllib.request
from pathlib import Path

LISTING = "https://huggingface.co/api/datasets/hotpotqa/hotpot_qa/parquet/distractor/validation"
RAW = Path("data/raw")
PARQUET = RAW / "hotpot_validation.parquet"
RECORDS = RAW / "hotpot_records.jsonl"
QUESTIONS = Path("data/hotpot_questions.jsonl")


def hp_doc_id(title: str, text: str) -> str:
    return "hp:" + hashlib.sha1(f"{title}\n{text}".encode()).hexdigest()[:16]


def download() -> None:
    if PARQUET.exists():
        return
    RAW.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(LISTING, timeout=60) as r:
        url = json.load(r)[0]
    print("downloading", url)
    urllib.request.urlretrieve(url, PARQUET)


def load_questions() -> list[dict]:
    import pyarrow.parquet as pq

    out = []
    for row in pq.read_table(PARQUET).to_pylist():
        paragraphs = []
        for title, sentences in zip(row["context"]["title"], row["context"]["sentences"]):
            text = " ".join(s.strip() for s in sentences if s.strip())
            paragraphs.append({"doc_id": hp_doc_id(title, text), "title": title, "text": text})
        gold_titles = set(row["supporting_facts"]["title"])
        out.append({
            "id": row["id"], "question": row["question"], "answer": row["answer"], "type": row["type"],
            "level": row["level"], "paragraphs": paragraphs,
            "gold_docs": [p["doc_id"] for p in paragraphs if p["title"] in gold_titles],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-records", type=int, default=65_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    download()
    questions = load_questions()
    raw_count = sum(len(q["paragraphs"]) for q in questions)
    unique_all = {p["doc_id"] for q in questions for p in q["paragraphs"]}

    kept_questions = questions
    if len(unique_all) > args.max_records:
        rng = random.Random(args.seed)
        order = list(range(len(questions)))
        rng.shuffle(order)
        kept_ids, kept_questions = set(), []
        for i in order:
            new = {p["doc_id"] for p in questions[i]["paragraphs"]} - kept_ids
            if len(kept_ids) + len(new) > args.max_records:
                continue
            kept_ids |= new
            kept_questions.append(questions[i])
        kept_questions.sort(key=lambda q: q["id"])

    records: dict[str, dict] = {}
    for q in kept_questions:
        for p in q["paragraphs"]:
            records.setdefault(p["doc_id"], p)
    if len(records) < 50_000:
        raise SystemExit(f"only {len(records)} records; need at least 50,000")

    RAW.mkdir(parents=True, exist_ok=True)
    with RECORDS.open("w") as f:
        for r in records.values():
            f.write(json.dumps(r) + "\n")
    with QUESTIONS.open("w") as f:
        for q in kept_questions:
            f.write(json.dumps({k: q[k] for k in ("id", "question", "answer", "type", "level", "gold_docs")}) + "\n")

    print(f"questions: {len(questions)} total, {len(kept_questions)} kept (seed {args.seed})")
    print(f"paragraphs: {raw_count} raw, {len(unique_all)} unique, {len(records)} kept")
    print(f"wrote {RECORDS} and {QUESTIONS}")


if __name__ == "__main__":
    main()
