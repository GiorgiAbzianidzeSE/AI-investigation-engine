import pytest

from eval.metrics import (aggregate, citation_precision, contains, correctness, ranked_docs, recall_at_k,
                          reciprocal_rank, token_f1)


def test_contains_rules():
    assert contains("Latency was about 900ms.", "900 ms")
    assert contains("It lasted 2 hours 45 minutes", "2 h 45 min|2 hours 45")
    assert contains("No. It was MailRelay.", "no")
    assert not contains("It was not internal", "no")  # short needles need a whole word
    assert contains("Owned by the CORE-BANKING team", "Core Banking")
    assert not contains("anything", "")  # empty needle never matches


def test_retrieval_metrics():
    ranked = ranked_docs(["d1", "d1", "g1", "d2", "g2"])
    assert ranked == ["d1", "g1", "d2", "g2"]
    assert recall_at_k(ranked, ["g1", "g2"], 2) == 0.5
    assert recall_at_k(ranked, ["g1", "g2"], 5) == 1.0
    assert reciprocal_rank(ranked, ["g1", "g2"]) == 0.5
    assert reciprocal_rank(ranked, ["zz"]) == 0.0


def result(status, answer="", claims=(), conflicts=(), sources=()):
    return {"status": status, "answer": answer, "claims": list(claims), "conflicts": list(conflicts),
            "sources": list(sources)}


SRC = [{"chunk_id": "c1", "doc_id": "g1"}, {"chunk_id": "c2", "doc_id": "g2"}, {"chunk_id": "c3", "doc_id": "x"}]


def test_correctness_answerable():
    q = {"type": "simple", "must_include": ["CHG-0331", "200"], "gold_docs": ["g1"]}
    assert correctness(q, result("answered", "CHG-0331 raised the pool to 200")) == 1.0
    assert correctness(q, result("answered", "CHG-0331 raised it")) == 0.0
    assert correctness(q, result("insufficient_evidence", "CHG-0331 200")) == 0.0
    assert correctness(q, result("answered", "see claims", [{"text": "CHG-0331 set 200", "citations": []}])) == 1.0


def test_correctness_unanswerable_and_contradictory():
    assert correctness({"type": "unanswerable"}, result("insufficient_evidence")) == 1.0
    assert correctness({"type": "unanswerable"}, result("answered")) == 0.0
    q = {"type": "contradictory", "conflict_sides": [["g1"], ["g2"]]}
    both = [{"topic": "t", "positions": [{"claim": "a", "citations": ["c1"]}, {"claim": "b", "citations": ["c2"]}]}]
    one = [{"topic": "t", "positions": [{"claim": "a", "citations": ["c1"]}, {"claim": "b", "citations": ["c3"]}]}]
    assert correctness(q, result("conflicting_evidence", conflicts=both, sources=SRC)) == 1.0
    assert correctness(q, result("conflicting_evidence", conflicts=one, sources=SRC)) == 0.5
    assert correctness(q, result("answered", sources=SRC)) == 0.0


def test_citation_precision_and_f1():
    q = {"gold_docs": ["g1", "g2"]}
    r = result("answered", claims=[{"text": "t", "citations": ["c1", "c3"]}], sources=SRC)
    assert citation_precision(q, r) == 0.5
    assert citation_precision(q, result("answered")) is None
    assert token_f1("the Yoruba people", "The Yoruba") == pytest.approx(0.8)


def test_aggregate():
    rows = [{"type": "a", "x": 1.0}, {"type": "a", "x": 0.0}, {"type": "b", "x": None}]
    agg = aggregate(rows, ["x"])
    assert agg["all"] == {"x": 0.5, "n": 3} and agg["b"] == {"x": None, "n": 1}
