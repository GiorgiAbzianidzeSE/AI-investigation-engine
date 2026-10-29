from app.investigate.citations import validate
from app.search.store import Hit

EV = {cid: Hit(cid, cid.split("#")[0], f"title {cid}", f"text of {cid}", payload={"date": "2026-03-05"})
      for cid in ("d1#b0", "d2#b0", "d3#b0")}


def test_invented_citation_dropped_and_sources_in_citation_order():
    r = validate({"status": "answered", "answer": "x", "claims": [
        {"text": "fact one", "citations": ["d2#b0", "made-up#b9"]},
        {"text": "fact two", "citations": ["[d1#b0]", "d2#b0"]},
    ]}, EV)
    assert r["status"] == "answered"
    assert r["claims"][0]["citations"] == ["d2#b0"]
    assert r["dropped_citations"] == 1
    assert [s["chunk_id"] for s in r["sources"]] == ["d2#b0", "d1#b0"]
    assert r["sources"][0]["date"] == "2026-03-05"


def test_claim_without_valid_citation_dropped_and_abstains():
    r = validate({"status": "answered", "answer": "x", "claims": [
        {"text": "uncited", "citations": []}, {"text": "fake", "citations": ["nope"]}]}, EV)
    assert r["claims"] == [] and r["sources"] == []
    assert r["status"] == "insufficient_evidence"


def test_conflicts_force_conflicting_status():
    r = validate({"status": "answered", "answer": "x", "claims": [{"text": "a", "citations": ["d1#b0"]}],
                  "conflicts": [{"topic": "duration", "positions": [
                      {"claim": "3 h 40 min", "citations": ["d1#b0"]},
                      {"claim": "about 2 hours", "citations": ["d2#b0"]}]}]}, EV)
    assert r["status"] == "conflicting_evidence"
    assert len(r["conflicts"][0]["positions"]) == 2


def test_conflict_with_one_valid_side_is_removed():
    r = validate({"status": "conflicting_evidence", "answer": "x",
                  "claims": [{"text": "a", "citations": ["d1#b0"]}],
                  "conflicts": [{"topic": "t", "positions": [
                      {"claim": "p1", "citations": ["d1#b0"]}, {"claim": "p2", "citations": ["ghost"]}]}]}, EV)
    assert r["conflicts"] == [] and r["status"] == "answered"


def test_garbage_is_safe():
    r = validate({"status": "weird", "claims": "nope", "conflicts": [1, None], "missing": ["x", ""]}, EV)
    assert r["status"] == "insufficient_evidence" and r["missing"] == ["x"]
