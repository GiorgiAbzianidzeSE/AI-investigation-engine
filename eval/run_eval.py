"""Evaluation runner.

    uv run python -m eval.run_eval --experiments e1,e2          # retrieval only: fast, no LLM
    uv run python -m eval.run_eval --experiments sweep          # ranker weight sweep on 10 questions
    uv run python -m eval.run_eval --experiments e3 [--limit N] [--configs b-full,a-full]

E1  retrieval method: dense / sparse / rrf / full, strategy B, all questions with gold documents
E2  chunking: strategy A vs B, mode full, incident questions only
E3  end to end through the agent (LLM responses cached in eval/results/llm.cache.json)

Each config writes eval/results/<experiment>-<config>.json (per-question rows + aggregates) and prints a markdown
table. E3 is resumable: questions already in the results file are skipped.
"""
import argparse
import json
import time
from pathlib import Path

from app.config import Settings, get_settings
from eval.metrics import (aggregate, citation_precision, correctness, has_correct_citation, ranked_docs,
                          recall_at_k, reciprocal_rank, token_f1)

QUESTIONS = Path("eval/questions.jsonl")
RESULTS = Path("eval/results")
RETRIEVAL_KEYS = ["recall@5", "recall@10", "mrr"]
E3_KEYS = ["correct", "f1", "citation_precision", "citation_support", "latency_s", "llm_calls", "tokens",
           "steps", "dropped_citations"]
SWEEP_IDS = ["S2", "S7", "M1", "M2", "M3", "M7", "X1", "X4", "HB1", "HC1"]


def load_questions() -> list[dict]:
    return [json.loads(line) for line in QUESTIONS.open()]


def build(settings: Settings):
    from app.search.embedder import Embedder
    from app.search.hybrid import HybridSearcher
    from app.search.store import QdrantStore

    store = QdrantStore(settings)
    return store, HybridSearcher(store, Embedder(settings), settings)


# ---------------------------------------------------------------- retrieval experiments
def retrieval_rows(searcher, questions, strategy: str, mode: str) -> list[dict]:
    rows = []
    for q in questions:
        hits = searcher.search(q["question"], strategy=strategy, mode=mode, top_k=30)
        ranked = ranked_docs([h.doc_id for h in hits])
        rows.append({"id": q["id"], "type": q["type"], "ranked": ranked[:10],
                     "recall@5": recall_at_k(ranked, q["gold_docs"], 5),
                     "recall@10": recall_at_k(ranked, q["gold_docs"], 10),
                     "mrr": reciprocal_rank(ranked, q["gold_docs"], 10)})
    return rows


def run_retrieval(name: str, searcher, questions, configs: list[tuple[str, str]]) -> dict:
    summary = {}
    for strategy, mode in configs:
        rows = retrieval_rows(searcher, questions, strategy, mode)
        agg = aggregate(rows, RETRIEVAL_KEYS)
        save(f"{name}-{strategy}-{mode}", rows, agg)
        summary[f"{strategy}-{mode}"] = agg
    print_table(name, summary, RETRIEVAL_KEYS)
    return summary


def run_sweep(searcher, questions) -> None:
    qs = [q for q in questions if q["id"] in SWEEP_IDS]
    base = searcher.weights
    results = []
    for wb in (0.0, 0.15, 0.3, 0.5):
        for wq in (0.0, 0.1, 0.2, 0.4):
            searcher.weights = type(base)(**{**base.__dict__, "w_bridge": wb, "w_query": wq})
            agg = aggregate(retrieval_rows(searcher, qs, "b", "full"), RETRIEVAL_KEYS)["all"]
            results.append({"w_bridge": wb, "w_query": wq, **agg})
    searcher.weights = base
    save("sweep-b-full", results, {"questions": SWEEP_IDS})
    print(f"\n### Ranker weight sweep ({len(qs)} questions, strategy B, w_rrf = 1.0)\n")
    print("| w_bridge | w_query | recall@5 | recall@10 | MRR |\n|---|---|---|---|---|")
    for r in results:
        print(f"| {r['w_bridge']} | {r['w_query']} | {r['recall@5']} | {r['recall@10']} | {r['mrr']} |")


# ---------------------------------------------------------------- end to end
def run_e3(settings: Settings, questions, configs: list[str], limit: int | None, pause: float) -> None:
    from app.investigate.agent import Investigator
    from app.llm.provider import LLMProvider, LLMUnavailable

    settings = settings.model_copy(update={"llm_cache_path": str(RESULTS / "llm.cache.json")})
    store, searcher = build(settings)
    agent = Investigator(LLMProvider.from_settings(settings), searcher, store, settings)
    summary = {}
    for cfg in configs:
        strategy, mode = cfg.split("-")
        name = f"e3-{cfg}"
        rows = load_rows(name)
        done = {r["id"] for r in rows}
        todo = [q for q in questions if q["id"] not in done][: limit or None]
        for i, q in enumerate(todo, 1):
            for attempt in range(3):
                try:
                    res = agent.investigate(q["question"], strategy=strategy, mode=mode)
                    break
                except LLMUnavailable as e:
                    wait = 60 * (attempt + 1)
                    print(f"  {q['id']}: LLM unavailable ({str(e)[:80]}...), waiting {wait}s")
                    time.sleep(wait)
            else:
                print(f"  {q['id']}: giving up for now (re-run later to resume)")
                break
            rows.append(e3_row(q, res))
            save(name, rows, aggregate(rows, E3_KEYS))
            r = rows[-1]
            print(f"  [{i}/{len(todo)}] {q['id']:4} {res['status']:22} correct={r['correct']} "
                  f"calls={r['llm_calls']} {r['latency_s']}s")
            if pause and not res["usage"]["cache_hits"] == res["usage"]["llm_calls"]:
                time.sleep(pause)
        summary[cfg] = aggregate(rows, E3_KEYS)
        save(name, rows, summary[cfg])
    print_table("e3", summary, E3_KEYS)


def e3_row(q: dict, res: dict) -> dict:
    u = res["usage"]
    answerable = q["type"] not in ("unanswerable",)
    return {
        "id": q["id"], "type": q["type"], "question": q["question"], "expect_status": q["expect_status"],
        "status": res["status"], "answer": res["answer"],
        "correct": correctness(q, res),
        "f1": token_f1(res["answer"], " ".join(q["must_include"])) if q["must_include"] else None,
        "citation_precision": citation_precision(q, res) if answerable else None,
        "citation_support": (1.0 if has_correct_citation(q, res) else 0.0)
        if answerable and res["status"] != "insufficient_evidence" else None,
        "latency_s": round(u["latency_ms"] / 1000, 2), "llm_calls": u["llm_calls"],
        "tokens": u["input_tokens"] + u["output_tokens"], "cache_hits": u["cache_hits"],
        "steps": len(res["trace"]), "dropped_citations": res["dropped_citations"],
        "cited_docs": sorted({s["doc_id"] for s in res["sources"]}), "trace": res["trace"],
        "conflicts": res["conflicts"], "missing": res["missing"], "error": res.get("error"),
    }


# ---------------------------------------------------------------- io
def save(name: str, rows: list, agg: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps({"aggregate": agg, "rows": rows}, indent=1))


def load_rows(name: str) -> list[dict]:
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text())["rows"] if path.exists() else []


def print_table(name: str, summary: dict, keys: list[str]) -> None:
    for cfg, agg in summary.items():
        print(f"\n### {name.upper()} - {cfg}\n")
        print("| type | n | " + " | ".join(keys) + " |")
        print("|---|---|" + "---|" * len(keys))
        for t, vals in agg.items():
            print(f"| {t} | {vals['n']} | " + " | ".join("-" if vals[k] is None else str(vals[k]) for k in keys) + " |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="e1,e2")
    ap.add_argument("--configs", default="b-full", help="E3 configs, e.g. b-full,a-full")
    ap.add_argument("--limit", type=int, default=None, help="E3: at most N new questions per config")
    ap.add_argument("--pause", type=float, default=0.0, help="E3: seconds to sleep between uncached questions")
    args = ap.parse_args()

    settings = get_settings()
    questions = load_questions()
    exps = {e.strip() for e in args.experiments.split(",")}
    with_gold = [q for q in questions if q["gold_docs"]]
    if exps & {"e1", "e2", "sweep"}:
        _, searcher = build(settings)
        if "e1" in exps:
            run_retrieval("e1", searcher, with_gold, [("b", m) for m in ("dense", "sparse", "rrf", "full")])
        if "e2" in exps:
            incident = [q for q in with_gold if q["corpus"] == "incidents"]
            run_retrieval("e2", searcher, incident, [("a", "full"), ("b", "full")])
        if "sweep" in exps:
            run_sweep(searcher, questions)
    if "e3" in exps:
        run_e3(settings, questions, args.configs.split(","), args.limit, args.pause)


if __name__ == "__main__":
    main()
