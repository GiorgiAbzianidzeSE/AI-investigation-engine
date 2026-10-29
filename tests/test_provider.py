import json
from types import SimpleNamespace

import pytest

from app.llm.provider import SKIP_SIGNATURE, Endpoint, LLMProvider, LLMUnavailable


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


def test_gemini_thought_signature_kept_for_gemini_only():
    sig = {"google": {"thought_signature": "abc"}}
    tc = SimpleNamespace(id="c1", extra_content=sig,
                         function=SimpleNamespace(name="search_corpus", arguments="{}"))
    gem = FakeClient([ok_response(None, [tc])])
    r = LLMProvider([Endpoint("gemini:a", gem, "a")], sleep=lambda s: None).chat([{"role": "user", "content": "q"}])
    assert r.tool_calls[0]["extra_content"] == sig and r.tool_calls[0]["endpoint"] == "gemini:a"

    history = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "search_corpus", "arguments": "{}"},
         "extra_content": sig, "endpoint": "gemini:a"}]}, {"role": "tool", "tool_call_id": "c1", "content": "[]"}]
    gem_a, gem_b = FakeClient([APIStatusError(429)] * 3), FakeClient([APIStatusError(429)] * 3)
    groq = FakeClient([ok_response("ok")])
    LLMProvider([Endpoint("gemini:a", gem_a, "a"), Endpoint("gemini:b", gem_b, "b"), Endpoint("groq:c", groq, "c")],
                sleep=lambda s: None).chat(history)

    def sent(client):
        return client.calls[0]["messages"][0]["tool_calls"][0]

    assert sent(gem_a)["extra_content"] == sig and "endpoint" not in sent(gem_a)
    assert sent(gem_b)["extra_content"] == SKIP_SIGNATURE
    assert "extra_content" not in sent(groq) and "endpoint" not in sent(groq)


def test_daily_quota_skips_endpoint_until_cooldown():
    daily = APIStatusError(429)
    daily.body = {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]}}
    now = [0.0]
    primary = FakeClient([daily, ok_response("primary again")])
    fallback = FakeClient([ok_response("a"), ok_response("b")])
    p = LLMProvider([Endpoint("p0", primary, "m"), Endpoint("p1", fallback, "m")], sleep=lambda s: None,
                    clock=lambda: now[0])
    assert p.chat([{"role": "user", "content": "1"}]).provider == "p1" and len(primary.calls) == 1
    assert p.chat([{"role": "user", "content": "2"}]).provider == "p1" and len(primary.calls) == 1
    now[0] = 3601
    assert p.chat([{"role": "user", "content": "3"}]).content == "primary again"


def test_model_chain_from_settings():
    from app.config import Settings

    s = Settings(gemini_api_key="k", gemini_model="m1, m2", groq_api_key="k", groq_model="g1", _env_file=None)
    assert LLMProvider.from_settings(s).names == ["gemini:m1", "gemini:m2", "groq:g1"]


def test_tool_calls_and_json_mode():
    tc = SimpleNamespace(id="", function=SimpleNamespace(name="search_corpus", arguments=json.dumps({"query": "q"})))
    c = FakeClient([ok_response(None, [tc])])
    r = provider(c).chat([], tools=[{"type": "function"}], json_mode=True)
    assert r.tool_calls == [{"id": "call_0", "name": "search_corpus", "arguments": {"query": "q"}}]
    assert c.calls[0]["response_format"] == {"type": "json_object"} and c.calls[0]["tools"]
