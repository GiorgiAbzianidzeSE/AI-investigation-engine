import json
from types import SimpleNamespace

import pytest

from app.llm.provider import Endpoint, LLMProvider, LLMUnavailable


class APIStatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APITimeoutError(Exception):
    pass


def ok_response(content="hi", tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                           usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.script.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def provider(*clients, **kw):
    eps = [Endpoint(f"p{i}", c, "m") for i, c in enumerate(clients)]
    return LLMProvider(eps, max_retries=2, sleep=lambda s: None, **kw)


def test_retry_then_succeed():
    c = FakeClient([APIStatusError(429), APITimeoutError(), ok_response("done")])
    r = provider(c).chat([{"role": "user", "content": "x"}])
    assert r.content == "done" and r.provider == "p0" and len(c.calls) == 3
    assert (r.input_tokens, r.output_tokens) == (7, 3)
    assert c.calls[0]["temperature"] == 0


def test_rate_limited_primary_falls_back():
    primary = FakeClient([APIStatusError(429)] * 3)
    fallback = FakeClient([ok_response("from fallback")])
    r = provider(primary, fallback).chat([{"role": "user", "content": "x"}])
    assert r.provider == "p1" and r.content == "from fallback"
    assert len(primary.calls) == 3


def test_non_retryable_skips_to_next_provider():
    primary = FakeClient([APIStatusError(401)])
    r = provider(primary, FakeClient([ok_response()])).chat([{"role": "user", "content": "x"}])
    assert r.provider == "p1" and len(primary.calls) == 1


def test_all_fail_raises():
    with pytest.raises(LLMUnavailable):
        provider(FakeClient([APIStatusError(500)] * 3), FakeClient([APIStatusError(400)])).chat([])


def test_no_endpoints_raises():
    with pytest.raises(LLMUnavailable):
        LLMProvider([])


def test_cache_hit_makes_no_call(tmp_path):
    path = tmp_path / "cache.json"
    c = FakeClient([ok_response("once")])
    p = provider(c, cache_path=str(path))
    msgs = [{"role": "user", "content": "x"}]
    assert not p.chat(msgs).cached
    second = p.chat(msgs)
    assert second.cached and second.content == "once" and len(c.calls) == 1
    # persisted: a new provider instance reads the file and still makes no call
    again = provider(FakeClient([]), cache_path=str(path)).chat(msgs)
    assert again.cached and again.content == "once"


def test_tool_calls_and_json_mode():
    tc = SimpleNamespace(id="", function=SimpleNamespace(name="search_corpus", arguments=json.dumps({"query": "q"})))
    c = FakeClient([ok_response(None, [tc])])
    r = provider(c).chat([], tools=[{"type": "function"}], json_mode=True)
    assert r.tool_calls == [{"id": "call_0", "name": "search_corpus", "arguments": {"query": "q"}}]
    assert c.calls[0]["response_format"] == {"type": "json_object"} and c.calls[0]["tools"]
