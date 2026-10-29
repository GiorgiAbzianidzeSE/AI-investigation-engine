"""Evaluation metrics (specs/06-evaluation.md). Pure functions over plain dicts."""
import re
import unicodedata
from collections import Counter


# ---------------------------------------------------------------- text matching
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def contains(text: str, needle: str) -> bool:
    """Case/punctuation-insensitive containment. "a|b" accepts either. Short needles ("no", "50") must be a
    whole word; longer ones also match with spaces removed ("900ms" == "900 ms", "2h 45min" == "2 h 45 min")."""
    norm = normalize(text)
    for alt in needle.split("|"):
        n = normalize(alt)
        if not n:
            continue
        if f" {n} " in f" {norm} ":
            return True
        if len(n.replace(" ", "")) > 3 and n.replace(" ", "") in norm.replace(" ", ""):
            return True
    return False


def token_f1(prediction: str, reference: str) -> float:
    p, r = normalize(prediction).split(), normalize(reference).split()
    common = sum((Counter(p) & Counter(r)).values())
    if not p or not r or not common:
        return 0.0
    precision, recall = common / len(p), common / len(r)
    return 2 * precision * recall / (precision + recall)


# ---------------------------------------------------------------- retrieval
def ranked_docs(doc_ids: list[str]) -> list[str]:
    """Collapse a ranked chunk list to documents; the first occurrence keeps the rank."""
    seen, out = set(), []
    for d in doc_ids:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def recall_at_k(ranked: list[str], gold: list[str], k: int) -> float:
    return len(set(ranked[:k]) & set(gold)) / len(set(gold)) if gold else 0.0


def reciprocal_rank(ranked: list[str], gold: list[str], k: int = 10) -> float:
    for i, d in enumerate(ranked[:k], 1):
        if d in gold:
            return 1.0 / i
    return 0.0


# ---------------------------------------------------------------- answers
def answer_text(result: dict) -> str:
    parts = [result.get("answer", "")]
    parts += [c["text"] for c in result.get("claims", [])]
    parts += [p["claim"] for c in result.get("conflicts", []) for p in c["positions"]]
    return "\n".join(parts)


def cited_doc_ids(result: dict) -> list[str]:
    by_chunk = {s["chunk_id"]: s["doc_id"] for s in result.get("sources", [])}
    cits = [c for cl in result.get("claims", []) for c in cl["citations"]]
    cits += [c for cf in result.get("conflicts", []) for p in cf["positions"] for c in p["citations"]]
    return [by_chunk[c] for c in cits if c in by_chunk]


def correctness(q: dict, result: dict) -> float:
    """1 = correct, 0.5 = partial (contradictory: right status, but the two sides' documents not both cited)."""
    status = result.get("status")
    if q["type"] == "unanswerable":
        return 1.0 if status == "insufficient_evidence" else 0.0
    if q["type"] == "contradictory":
        flagged = status == "conflicting_evidence" or bool(result.get("conflicts"))
        if not flagged:
            return 0.0
        conflict_docs = {d for cf in result.get("conflicts", []) for p in cf["positions"]
                         for d in _position_docs(p, result)}
        both = all(conflict_docs & set(side) for side in q.get("conflict_sides", []))
        return 1.0 if both else 0.5
    if status != "answered":
        return 0.0
    text = answer_text(result)
    return 1.0 if all(contains(text, m) for m in q["must_include"]) else 0.0


def content_correct(q: dict, result: dict) -> float | None:
    """Answerable questions only: every must_include appears, whatever the status. Separates "wrong answer"
    from "right answer, but the agent also surfaced a real conflict in the corpus" (strict correctness = 0)."""
    if q["type"] in ("unanswerable", "contradictory") or not q["must_include"]:
        return None
    text = answer_text(result)
    return 1.0 if all(contains(text, m) for m in q["must_include"]) else 0.0


def _position_docs(position: dict, result: dict) -> list[str]:
    by_chunk = {s["chunk_id"]: s["doc_id"] for s in result.get("sources", [])}
    return [by_chunk[c] for c in position["citations"] if c in by_chunk]


def citation_precision(q: dict, result: dict) -> float | None:
    """Share of cited chunks whose document is a gold document; None when nothing was cited or no gold."""
    cited = cited_doc_ids(result)
    if not cited or not q.get("gold_docs"):
        return None
    return sum(d in q["gold_docs"] for d in cited) / len(cited)


def has_correct_citation(q: dict, result: dict) -> bool:
    return any(d in q.get("gold_docs", []) for d in cited_doc_ids(result))


# ---------------------------------------------------------------- aggregation
def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def aggregate(rows: list[dict], keys: list[str]) -> dict:
    """Overall and per-type means of the given numeric keys."""
    out = {"all": {k: mean(r.get(k) for r in rows) for k in keys} | {"n": len(rows)}}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        out[t] = {k: mean(r.get(k) for r in sub) for k in keys} | {"n": len(sub)}
    return out
