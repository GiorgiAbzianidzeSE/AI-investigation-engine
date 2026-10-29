"""Agentic RAG loop: the model plans and calls tools, then a separate step writes the cited answer.

    tool phase  : up to MAX_STEPS rounds of search_corpus / get_document, until the model calls finish
    safety net  : no evidence at all -> one search with the question itself
    synthesis   : JSON answer from the numbered evidence list only (one repair retry on invalid JSON)
    validation  : citations.validate drops anything not backed by the evidence set
"""
import hashlib
import json
import logging
import re
import time

from app.config import Settings
from app.investigate.citations import validate
from app.investigate.tools import TOOL_SCHEMAS, Toolbox
from app.llm.prompts import REPAIR, SYNTHESIS_SYSTEM, TOOL_SYSTEM, evidence_block
from app.llm.provider import Usage

log = logging.getLogger(__name__)

MODES = ("dense", "sparse", "rrf", "full")
STRATEGIES = ("a", "b")


class Investigator:
    def __init__(self, llm, searcher, store, settings: Settings):
        self.llm, self.searcher, self.store, self.s = llm, searcher, store, settings

    def investigate(self, question: str, strategy: str | None = None, mode: str = "full") -> dict:
        t0 = time.perf_counter()
        strategy = strategy or self.s.default_strategy
        if strategy not in STRATEGIES or mode not in MODES:
            raise ValueError(f"strategy must be one of {STRATEGIES} and mode one of {MODES}")
        usage = Usage()
        tools = Toolbox(self.searcher, self.store, strategy, mode, self.s.top_k)
        trace = self._tool_phase(question, tools, usage)

        if not tools.evidence:
            hits = tools.search_corpus(question)
            trace.append({"step": len(trace) + 1, "tool": "search_corpus", "args": {"query": question},
                          "results": len(hits), "auto": True})

        evidence = tools.for_synthesis(self.s.max_evidence)
        final, error = self._synthesize(question, evidence, usage)
        result = validate(final, {h.chunk_id: h for h in evidence})
        if error:
            result["error"] = error
        if not result["answer"]:
            result["answer"] = ("The documents do not contain enough evidence to answer this question."
                                if result["status"] == "insufficient_evidence" else "")

        latency_ms = int((time.perf_counter() - t0) * 1000)
        result.update({
            "trace": trace,
            "usage": {"llm_calls": usage.llm_calls, "cache_hits": usage.cache_hits,
                      "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                      "providers": usage.providers, "latency_ms": latency_ms},
            "config": {"strategy": strategy, "mode": mode},
            "evidence_count": len(evidence),
        })
        log.info("investigate q=%s status=%s steps=%d calls=%d tokens=%d/%d dropped=%d latency_ms=%d",
                 hashlib.sha1(question.encode()).hexdigest()[:10], result["status"], len(trace), usage.llm_calls,
                 usage.input_tokens, usage.output_tokens, result["dropped_citations"], latency_ms)
        return result

    def _tool_phase(self, question: str, tools: Toolbox, usage: Usage) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": TOOL_SYSTEM}, {"role": "user", "content": question}]
        trace: list[dict] = []
        for _ in range(self.s.max_steps):
            reply = self.llm.chat(messages, tools=TOOL_SCHEMAS)
            usage.add(reply)
            if not reply.tool_calls:
                break
            messages.append({
                "role": "assistant", "content": reply.content or "",
                "tool_calls": [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                                **({"extra_content": tc["extra_content"]} if tc.get("extra_content") else {})}
                               for tc in reply.tool_calls],
            })
            finished = False
            for tc in reply.tool_calls:
                if tc["name"] == "finish":
                    finished = True
                    output, n = json.dumps({"ok": True}), 0
                else:
                    output, n = tools.run(tc["name"], tc["arguments"])
                trace.append({"step": len(trace) + 1, "tool": tc["name"], "args": tc["arguments"], "results": n})
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": output})
            if finished:
                break
        return trace

    def _synthesize(self, question: str, evidence: list, usage: Usage) -> tuple[dict, str | None]:
        messages = [{"role": "system", "content": SYNTHESIS_SYSTEM},
                    {"role": "user", "content": evidence_block(question, evidence)}]
        reply = self.llm.chat(messages, json_mode=True)
        usage.add(reply)
        parsed = parse_json(reply.content)
        if parsed is None:
            messages += [{"role": "assistant", "content": reply.content or ""}, {"role": "user", "content": REPAIR}]
            reply = self.llm.chat(messages, json_mode=True)
            usage.add(reply)
            parsed = parse_json(reply.content)
        if parsed is None:
            return {"status": "insufficient_evidence",
                    "answer": "The model did not return a valid answer, so no answer is given."}, \
                "invalid_model_output"
        return parsed, None


def parse_json(text: str | None) -> dict | None:
    """Parse the model's JSON, tolerating a ```json fence or prose around a single object."""
    if not text:
        return None
    for candidate in (text, *re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)):
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None
