import pytest

from app.config import Settings
from app.ingest.pipeline import IngestPipeline
from app.investigate.agent import Investigator, parse_json
from app.llm.provider import LLMUnavailable
from app.search.hybrid import HybridSearcher
from tests.fakes import FakeEmbedder, FakeLLM, FakeStore, tool_call

SETTINGS = Settings(_env_file=None, chunk_words=40, chunk_overlap=5)
INC = b"# INC-2041 report\n\nCard authorizations failed on 2026-03-05. Root cause: CHG-0314 slowed fraud-scorer."
CHG = b"# CHG-0314 change request\n\nfraud-scorer model v4 rollout. Approver: blank."


@pytest.fixture
def services():
    store = FakeStore()
    pipe = IngestPipeline(store, FakeEmbedder(), SETTINGS)
    pipe.add_file("inc.md", INC, source="incidents")
    pipe.add_file("chg.md", CHG, source="incidents")
    return store, HybridSearcher(store, FakeEmbedder(), SETTINGS)


def make(services, replies):
    store, searcher = services
    llm = FakeLLM(replies)
    return Investigator(llm, searcher, store, SETTINGS), llm


def chunk_of(store, doc_id, strategy="b"):
    return next(c for c, v in store.chunks.items() if v["payload"]["doc_id"] == doc_id
                and v["payload"]["strategy"] == strategy)


def test_scripted_tool_calls_produce_trace_and_cited_answer(services):
    store, _ = services
    inc_chunk = chunk_of(store, "incidents:inc-md")
    agent, llm = make(services, [
        {"tool_calls": [tool_call("search_corpus", query="INC-2041 root cause")]},
        {"tool_calls": [tool_call("get_document", doc_id="incidents:chg-md")]},
        {"tool_calls": [tool_call("finish", reason="done")]},
        {"content": {"status": "answered", "answer": "CHG-0314.",
                     "claims": [{"text": "CHG-0314 slowed fraud-scorer", "citations": [inc_chunk, "invented#b1"]}]}},
    ])
    r = agent.investigate("What caused INC-2041?")
    assert r["status"] == "answered"
    assert [t["tool"] for t in r["trace"]] == ["search_corpus", "get_document", "finish"]
    assert r["trace"][0]["results"] > 0 and r["trace"][0]["args"] == {"query": "INC-2041 root cause"}
    assert r["sources"][0]["chunk_id"] == inc_chunk
    assert r["dropped_citations"] == 1
    assert r["usage"]["llm_calls"] == 4 and r["usage"]["input_tokens"] == 40
    assert r["config"] == {"strategy": "b", "mode": "full"}
    # the tool result was fed back to the model with the matching tool_call_id
    second_call_msgs = llm.calls[1]["messages"]
    assert second_call_msgs[-1]["role"] == "tool" and "INC-2041" in second_call_msgs[-1]["content"]
    assert llm.calls[-1]["json_mode"] and llm.calls[-1]["tools"] is None


def test_no_tool_calls_triggers_safety_net_search(services):
    store, _ = services
    agent, llm = make(services, [
        {"content": "I already know the answer."},
        {"content": {"status": "answered", "answer": "x",
                     "claims": [{"text": "y", "citations": [chunk_of(store, "incidents:inc-md")]}]}},
    ])
    r = agent.investigate("What caused INC-2041?")
    assert r["trace"][-1].get("auto") is True and r["evidence_count"] > 0
    assert "Evidence:" in llm.calls[-1]["messages"][-1]["content"]
    assert r["status"] == "answered"


def test_invalid_json_repair_then_abstain(services):
    agent, llm = make(services, [{"content": "no tools"}, {"content": "not json"}, {"content": "still not json"}])
    r = agent.investigate("What caused INC-2041?")
    assert r["status"] == "insufficient_evidence" and r["error"] == "invalid_model_output"
    assert r["claims"] == [] and r["usage"]["llm_calls"] == 3


def test_invalid_json_repaired(services):
    store, _ = services
    cid = chunk_of(store, "incidents:chg-md")
    agent, _ = make(services, [{"content": "no tools"}, {"content": "oops"},
                               {"content": f'```json\n{{"status": "answered", "answer": "a", '
                                           f'"claims": [{{"text": "t", "citations": ["{cid}"]}}]}}\n```'}])
    r = agent.investigate("Who approved CHG-0314?")
    assert r["status"] == "answered" and "error" not in r


def test_max_steps_bounds_the_loop(services):
    replies = [{"tool_calls": [tool_call("search_corpus", query=f"q{i}")]} for i in range(SETTINGS.max_steps)]
    agent, llm = make(services, replies + [{"content": {"status": "insufficient_evidence", "answer": "",
                                                        "missing": ["approver"]}}])
    r = agent.investigate("Who approved CHG-0314?")
    assert len(r["trace"]) == SETTINGS.max_steps
    assert r["status"] == "insufficient_evidence" and r["missing"] == ["approver"] and r["answer"]


def test_unknown_tool_and_bad_doc_are_reported_to_model(services):
    agent, llm = make(services, [
        {"tool_calls": [tool_call("get_document", doc_id="nope"), tool_call("delete_everything")]},
        {"tool_calls": [tool_call("finish", reason="x")]},
        {"content": {"status": "insufficient_evidence", "answer": "nothing"}},
    ])
    agent.investigate("anything")
    tool_msgs = [m for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert "unknown doc_id" in tool_msgs[0]["content"] and "unknown tool" in tool_msgs[1]["content"]


def test_llm_unavailable_propagates(services):
    agent, _ = make(services, [LLMUnavailable("all down")])
    with pytest.raises(LLMUnavailable):
        agent.investigate("x")


def test_bad_config_rejected(services):
    agent, _ = make(services, [])
    with pytest.raises(ValueError):
        agent.investigate("x", mode="magic")


def test_parse_json_variants():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('Here: {"a": 1} thanks') == {"a": 1}
    assert parse_json("[1, 2]") is None and parse_json(None) is None
