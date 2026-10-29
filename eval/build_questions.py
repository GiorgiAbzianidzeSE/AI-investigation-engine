"""Write eval/questions.jsonl: 28 incident questions (specs/appendix-b) + 14 seeded HotpotQA questions.

    uv run python -m eval.build_questions

must_include: every entry must appear in the answer (case/punctuation-insensitive); "a|b" = either a or b.
conflict_sides (contradictory questions): the gold documents of each side; a correct answer cites both.
"""
import json
import random
from pathlib import Path

OUT = Path("eval/questions.jsonl")
HOTPOT = Path("data/hotpot_questions.jsonl")
SEED = 42

D = {  # Appendix A document numbers -> doc_id
    1: "changelog-march-2026-md", 2: "chg-0311-change-request-docx", 3: "chg-0314-change-request-docx",
    4: "chg-0320-change-request-docx", 5: "chg-0327-change-request-docx", 6: "chg-0331-change-request-docx",
    7: "inc-2041-incident-report-pdf", 8: "inc-2047-incident-report-pdf", 9: "inc-2052-incident-report-pdf",
    10: "pm-2041-postmortem-pdf", 11: "status-page-march-2026-html", 12: "finance-summary-march-2026-html",
    13: "service-catalog-html", 14: "fraud-scorer-runbook-md", 15: "payments-architecture-md",
    16: "ops-review-march-2026-pdf",
}


def docs(*nums: int) -> list[str]:
    return [f"incidents:{D[n]}" for n in nums]


def q(id_, type_, question, must=(), gold=(), sides=None):
    status = {"unanswerable": "insufficient_evidence", "contradictory": "conflicting_evidence"}.get(type_, "answered")
    row = {"id": id_, "type": type_, "corpus": "incidents", "question": question, "must_include": list(must),
           "gold_docs": docs(*gold), "expect_status": status}
    if sides:
        row["conflict_sides"] = [docs(*s) for s in sides]
    return row


INCIDENT_QUESTIONS = [
    q("S1", "simple", "When was CHG-0314 deployed?", ["2026-03-05|March 5"], (3, 1)),
    q("S2", "simple", "What did CHG-0311 change?", ["connection pool", "50"], (2, 1)),
    q("S3", "simple", "How long did INC-2047 last?", ["2 h 45 min|2 hours 45|2 hours and 45|2h 45"], (8,)),
    q("S4", "simple", "Which team owns ledger-service?", ["Core Banking"], (13,)),
    q("S5", "simple", "What change was made on 2026-03-24?", ["CHG-0331", "200"], (6, 1)),
    q("S6", "simple", "What caused the notification email delays on March 26?", ["MailRelay"], (9,)),
    q("S7", "simple", "What p99 latency did fraud-scorer show after the v4 model rollout?", ["900 ms"], (7,)),
    q("S8", "simple", "When does reconciliation-job run?", ["00:00", "01:30"], (15, 13)),
    q("M1", "multi_doc", "Which system changes caused payment-processing delays in March 2026, which services were "
                         "affected, and which documents prove it?",
      ["CHG-0314", "CHG-0311", "CHG-0327", "payments-gateway", "ledger-service", "settlement-batch"], (7, 8, 2, 3, 5)),
    q("M2", "multi_doc", "Which change caused merchant payouts to be late on March 19, and why did it conflict with "
                         "another job?", ["CHG-0327", "reconciliation-job", "lock"], (8, 5, 15)),
    q("M3", "multi_doc", "Why did a fraud model update slow down card authorizations?",
      ["synchronous", "fraud-scorer", "payments-gateway"], (7, 15, 3)),
    q("M4", "multi_doc", "Was the ledger connection pool change ever reverted, and which incident led to that?",
      ["CHG-0331", "INC-2041"], (6, 7)),
    q("M5", "multi_doc", "Which service was affected by both INC-2041 and INC-2047?", ["ledger-service"], (7, 8)),
    q("M6", "multi_doc", "Which March 2026 change had no customer impact?", ["CHG-0320"], (4, 16)),
    q("M7", "multi_doc", "Which team requested the change that caused INC-2047, and which team owns "
                         "reconciliation-job?", ["Treasury Engineering", "Finance Ops Engineering"], (5, 8, 13)),
    q("M8", "multi_doc", "Was INC-2052 caused by any March system change?", ["no", "MailRelay"], (9, 16)),
    q("U1", "unanswerable", "What was the financial cost of INC-2041 in euros?"),
    q("U2", "unanswerable", "Who approved CHG-0314?"),
    q("U3", "unanswerable", "Which incidents happened in April 2026?"),
    q("U4", "unanswerable", "What is the SLA of auth-service?"),
    q("U5", "unanswerable", "Which outages affected the mobile-app service in March?"),
    q("U6", "unanswerable", "Who is the CEO of Northwind Payments?"),
    q("X1", "contradictory", "What was the root cause of INC-2041?", gold=(7, 11, 10), sides=[(7,), (11, 10)]),
    q("X2", "contradictory", "How long did INC-2041 last?", gold=(7, 11), sides=[(7, 10), (11,)]),
    q("X3", "contradictory", "How many merchants were affected by INC-2047?", gold=(8, 12), sides=[(8,), (12,)]),
    q("X4", "contradictory", "Which team owns fraud-scorer?", gold=(13, 14), sides=[(13,), (14,)]),
    q("X5", "contradictory", "Was fraud-scorer a contributing factor in INC-2041?", gold=(7, 10), sides=[(7,), (10,)]),
    q("X6", "contradictory", "Was INC-2041 caused by an external provider?", gold=(11, 7), sides=[(11,), (7, 10)]),
]


def hotpot_sample(n_per_type: int = 7) -> list[dict]:
    rows = [json.loads(line) for line in HOTPOT.open()]
    rng = random.Random(SEED)
    out = []
    for t in ("bridge", "comparison"):
        pool = sorted((r for r in rows if r["type"] == t and len(r["gold_docs"]) >= 2), key=lambda r: r["id"])
        for i, r in enumerate(rng.sample(pool, n_per_type), 1):
            out.append({"id": f"H{t[0].upper()}{i}", "type": "multi_hop", "corpus": "hotpotqa",
                        "hotpot_type": t, "question": r["question"], "must_include": [r["answer"]],
                        "gold_docs": r["gold_docs"], "expect_status": "answered"})
    return out


def main() -> None:
    rows = INCIDENT_QUESTIONS + hotpot_sample()
    with OUT.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} questions to {OUT}")


if __name__ == "__main__":
    main()
