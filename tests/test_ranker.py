import pytest

from app.config import Settings
from app.ingest.pipeline import IngestPipeline
from app.search.hybrid import HybridSearcher
from app.search.ranker import (RankWeights, bridge_scores, diversify, extract_entities, query_match, rank,
                               rrf_scores)
from app.search.store import Hit
from tests.fakes import FakeEmbedder, FakeStore


def hit(cid, doc, text="", title=None):
    return Hit(cid, doc, title or doc, text)


def test_entities():
    ents = extract_entities("Because CHG-0314 slowed fraud-scorer on 2026-03-05, the Bank of America and "
                            "Ed Wood met. Every end-to-end check passed in March.")
    assert {"chg-0314", "fraud-scorer", "date:03-05", "bank of america", "ed wood"} <= ents
    assert not {"because", "every", "chg", "end-to-end", "march"} & ents
    assert extract_entities("delays on March 26?") == {"date:03-26"}


def test_rrf_math():
    a, b, c = hit("a", "d1"), hit("b", "d2"), hit("c", "d3")
    s = rrf_scores([[a, b], [b, c]], k=60)
    assert s["a"] == pytest.approx(1 / 61)
    assert s["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert s["c"] == pytest.approx(1 / 62)


def test_bridge_counts_entities_shared_with_other_documents():
    hits = [hit("x", "inc", "INC-2041 was caused by CHG-0314"), hit("y", "chg", "CHG-0314 rolled out a model"),
            hit("z", "other", "unrelated text"), hit("x2", "inc", "INC-2041 timeline")]
    ents = {h.chunk_id: extract_entities(h.text) for h in hits}
    b = bridge_scores(hits, ents)
    assert b["x"] == 1.0 and b["y"] == 1.0
    assert b["z"] == 0.0
    assert b["x2"] == 0.0  # INC-2041 is only shared within its own document


def test_bridge_prefers_rare_links_over_hub_mentions():
    hub_id = "CHG-0001"
    hits = [hit("pair_a", "a", "CHG-0314 and CHG-0001"), hit("pair_b", "b", "CHG-0314 here")] + [
        hit(f"h{i}", f"hub{i}", f"{hub_id} mentioned") for i in range(4)]
    ents = {h.chunk_id: extract_entities(h.text) for h in hits}
    b = bridge_scores(hits, ents)
    assert b["pair_a"] == 1.0  # shares the rare CHG-0314 and the common CHG-0001
    assert b["pair_b"] > b["h0"]  # one rare link beats one mention of an id every document has


def test_bridge_boost_lifts_connecting_chunk_in_a_near_tie():
    plain = hit("plain", "d1", "general text about payments")
    link = hit("link", "d2", "INC-2041 was caused by CHG-0314")
    target = hit("t", "d3", "CHG-0314 change request")
    fillers = [hit(f"f{i}", f"doc{i}", "filler") for i in range(4)]
    dense = [plain, link, fillers[0], fillers[1], target]
    sparse = [plain, link, fillers[2], fillers[3], target]
    assert rank("q", dense, sparse, 3, mode="rrf")[0].chunk_id == "plain"
    full = rank("q", dense, sparse, 3, RankWeights(w_bridge=0.3, w_query=0.0), mode="full")
    assert full[0].chunk_id == "link"


def test_query_match_title_counts_double():
    q = extract_entities("What happened in INC-2041 to fraud-scorer?")
    h_text = hit("a", "d", "INC-2041 fraud-scorer", title="x")
    h_title = hit("b", "d", "nothing", title="INC-2041 fraud-scorer report")
    h_half = hit("c", "d", "INC-2041 only", title="x")
    assert query_match(q, h_text, extract_entities(h_text.text)) == 0.5  # both entities, body only
    assert query_match(q, h_title, set()) == 1.0  # both in the title
    assert query_match(q, h_half, extract_entities(h_half.text)) == 0.25
    assert query_match(q, hit("z", "d", "zzz"), set()) == 0.0
    assert query_match(set(), h_text, set()) == 0.0


def test_diversity_cap():
    hits = [hit(f"c{i}", "same") for i in range(5)] + [hit("o", "other")]
    out = diversify(hits, 3)
    assert [h.chunk_id for h in out] == ["c0", "c1", "c2", "o"]


def test_modes():
    d = [hit("d1", "A"), hit("d2", "B")]
    s = [hit("s1", "C"), hit("d2", "B")]
    assert [h.chunk_id for h in rank("q", d, s, 5, mode="dense")] == ["d1", "d2"]
    assert [h.chunk_id for h in rank("q", d, s, 5, mode="sparse")] == ["s1", "d2"]
    rrf = rank("q", d, s, 5, mode="rrf")
    assert rrf[0].chunk_id == "d2" and rrf[0].score == 1.0
    assert {h.chunk_id for h in rank("q", d, s, 5, mode="full")} == {"d1", "d2", "s1"}
    assert rank("q", [], [], 5) == []


def test_hybrid_search_end_to_end_with_fakes():
    s = Settings(_env_file=None, chunk_words=30, chunk_overlap=5)
    store = FakeStore()
    pipe = IngestPipeline(store, FakeEmbedder(), s)
    pipe.add_file("inc.md", b"# INC-2041\n\nCard authorizations failed. Root cause was CHG-0314 in fraud-scorer.")
    pipe.add_file("chg.md", b"# CHG-0314\n\nfraud-scorer model v4 rollout on 2026-03-05.")
    pipe.add_records([{"doc_id": "hp:1", "title": "Paris", "text": "Paris is the capital of France."}])
    searcher = HybridSearcher(store, FakeEmbedder(), s)
    for mode in ("dense", "sparse", "rrf", "full"):
        hits = searcher.search("What caused INC-2041?", strategy="b", mode=mode)
        assert hits and all(h.payload["strategy"] in ("b", "na") for h in hits)
    assert searcher.search("capital of France", strategy="a")[0].doc_id == "hp:1"
    only = searcher.search("fraud-scorer", doc_ids=["upload:chg-md"])
    assert {h.doc_id for h in only} == {"upload:chg-md"}
