"""Citation validation and abstention, enforced in code (the model's output is never trusted as-is).

1. cited chunk_ids that are not in the evidence set are dropped (invented ids)
2. claims and conflict positions left without a valid citation are dropped
3. a conflict with fewer than two positions left is removed
4. "answered" with no claims left -> "insufficient_evidence"
5. conflicts left and status "answered" -> "conflicting_evidence";
   "conflicting_evidence" with no conflicts left -> "answered" if claims remain, else "insufficient_evidence"
6. sources = only the chunks actually cited, in order of first citation
7. the number of dropped citations is reported
"""
from app.search.store import Hit

STATUSES = ("answered", "insufficient_evidence", "conflicting_evidence")
SNIPPET = 300


def validate(final: dict, evidence: dict[str, Hit]) -> dict:
    dropped = 0
    cited_order: list[str] = []

    def keep(citations) -> list[str]:
        nonlocal dropped
        valid = []
        for c in citations if isinstance(citations, list) else []:
            c = str(c).strip().strip("[]")
            if c in evidence and c not in valid:
                valid.append(c)
                if c not in cited_order:
                    cited_order.append(c)
            else:
                dropped += 1
        return valid

    claims = []
    for cl in final.get("claims") or []:
        if not isinstance(cl, dict):
            continue
        cits = keep(cl.get("citations"))
        if cits and str(cl.get("text", "")).strip():
            claims.append({"text": str(cl["text"]).strip(), "citations": cits})

    conflicts = []
    for cf in final.get("conflicts") or []:
        if not isinstance(cf, dict):
            continue
        positions = []
        for p in cf.get("positions") or []:
            if not isinstance(p, dict):
                continue
            cits = keep(p.get("citations"))
            if cits and str(p.get("claim", "")).strip():
                positions.append({"claim": str(p["claim"]).strip(), "citations": cits})
        if len(positions) >= 2:
            conflicts.append({"topic": str(cf.get("topic", "")).strip(), "positions": positions})

    status = final.get("status")
    if status not in STATUSES:
        status = "answered" if claims else "insufficient_evidence"
    if status == "answered" and not claims:
        status = "insufficient_evidence"
    if conflicts and status == "answered":
        status = "conflicting_evidence"
    if status == "conflicting_evidence" and not conflicts:
        status = "answered" if claims else "insufficient_evidence"

    # sources only from citations that survived (a claim dropped later can't leave an orphan source)
    used = {c for cl in claims for c in cl["citations"]} | {
        c for cf in conflicts for p in cf["positions"] for c in p["citations"]}
    sources = []
    for cid in cited_order:
        if cid in used:
            h = evidence[cid]
            sources.append({"chunk_id": cid, "doc_id": h.doc_id, "title": h.title,
                            "date": h.payload.get("date"), "snippet": h.text[:SNIPPET]})

    missing = [str(m) for m in final.get("missing") or [] if str(m).strip()]
    return {
        "status": status,
        "answer": str(final.get("answer") or "").strip(),
        "claims": claims,
        "conflicts": conflicts,
        "missing": missing,
        "sources": sources,
        "dropped_citations": dropped,
    }
