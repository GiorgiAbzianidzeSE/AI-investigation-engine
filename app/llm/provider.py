"""LLM access through OpenAI-compatible endpoints (Gemini primary, Groq fallback).

Error handling:
  - per-call timeout
  - retry with exponential backoff on rate limits (429), timeouts and 5xx
  - then fall back to the next provider
  - if every provider fails -> LLMUnavailable (the API turns it into a 503, never a fake answer)
Caching: identical requests are served from an in-memory dict, optionally persisted to a JSON file.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[dict]  # [{"id", "name", "arguments": dict}]
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


@dataclass
class Usage:
    llm_calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    providers: list[str] = field(default_factory=list)

    def add(self, r: LLMReply) -> None:
        self.llm_calls += 1
        self.cache_hits += r.cached
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        if r.provider not in self.providers:
            self.providers.append(r.provider)


@dataclass
class Endpoint:
    name: str
    client: object  # openai.OpenAI (or a fake in tests)
    model: str


class LLMProvider:
    def __init__(self, endpoints: list[Endpoint], max_retries: int = 2, cache_path: str | None = None,
                 sleep=time.sleep):
        if not endpoints:
            raise LLMUnavailable("No LLM configured: set GEMINI_API_KEY and/or GROQ_API_KEY")
        self.endpoints, self.max_retries, self.sleep = endpoints, max_retries, sleep
        self.names = [ep.name for ep in endpoints]
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())

    @classmethod
    def from_settings(cls, s: Settings) -> "LLMProvider":
        from openai import OpenAI

        endpoints = []
        if s.gemini_api_key:
            endpoints.append(Endpoint("gemini", OpenAI(api_key=s.gemini_api_key, base_url=s.gemini_base_url,
                                                       timeout=s.llm_timeout_s, max_retries=0), s.gemini_model))
        if s.groq_api_key:
            endpoints.append(Endpoint("groq", OpenAI(api_key=s.groq_api_key, base_url=s.groq_base_url,
                                                     timeout=s.llm_timeout_s, max_retries=0), s.groq_model))
        return cls(endpoints, s.llm_max_retries, s.llm_cache_path)

    def chat(self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False) -> LLMReply:
        key = hashlib.sha256(json.dumps([messages, tools, json_mode], sort_keys=True).encode()).hexdigest()
        if key in self.cache:
            return LLMReply(**{**self.cache[key], "cached": True})

        errors = []
        for ep in self.endpoints:
            for attempt in range(self.max_retries + 1):
                try:
                    reply = self._call(ep, messages, tools, json_mode)
                    self._remember(key, reply)
                    return reply
                except Exception as e:  # noqa: BLE001 - classified below
                    retryable = _is_retryable(e)
                    errors.append(f"{ep.name}: {type(e).__name__}: {str(e)[:200]}")
                    log.warning("LLM %s attempt %d failed (%s)", ep.name, attempt + 1, errors[-1])
                    if not retryable or attempt == self.max_retries:
                        break
                    self.sleep(min(20.0, 2.0 * 2 ** attempt))
        raise LLMUnavailable("; ".join(errors))

    def _call(self, ep: Endpoint, messages, tools, json_mode) -> LLMReply:
        kwargs = {"model": ep.model, "messages": messages, "temperature": 0}
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = ep.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for i, tc in enumerate(msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            # some OpenAI-compatible endpoints return empty ids; the follow-up tool message needs one
            calls.append({"id": tc.id or f"call_{i}", "name": tc.function.name, "arguments": args})
        usage = getattr(resp, "usage", None)
        return LLMReply(msg.content, calls, ep.name,
                        getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)

    def _remember(self, key: str, reply: LLMReply) -> None:
        self.cache[key] = {k: v for k, v in reply.__dict__.items() if k != "cached"}
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))


def _is_retryable(e: Exception) -> bool:
    status = getattr(e, "status_code", None)
    if status is not None:
        return status == 429 or status >= 500
    return type(e).__name__ in {"APITimeoutError", "APIConnectionError", "TimeoutError", "ConnectionError"}
