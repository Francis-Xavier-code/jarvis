"""Tests for provider streaming: SSE parsing, tool-call accumulation, usage.

The provider must tolerate kernels whose ChatChunk lacks a usage field
(core types do not hot-reload), so usage is attached defensively.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from jarvis.types import ChatMessage, ChatRequest, ToolSpec


def _load_provider():
    root = Path(__file__).resolve().parents[1] / "plugins" / "provider-openai" / "plugin.py"
    spec = importlib.util.spec_from_file_location("provider_openai_stream_test", root)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cfg:
    def get(self, k, d=""):
        if k == "provider-openai.openai_api_key":
            return "sk-test"
        if k == "provider-openai.openai_base_url":
            return "https://example.com/v1"
        return d


class _FakeKernel:
    config = _Cfg()


def _fake_requests(monkeypatch, mod, sse_lines):
    class FakeResp:
        status_code = 200
        text = ""

        def iter_lines(self, decode_unicode=True):
            return iter(sse_lines)

    class FakeRequests:
        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(mod, "requests", FakeRequests())


def test_provider_streams_text_and_usage(monkeypatch) -> None:
    mod = _load_provider()
    _fake_requests(monkeypatch, mod, [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
        "data: [DONE]",
    ])
    prov = mod.OpenAIProvider(_FakeKernel())
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=[], model="m")
    chunks = list(prov.chat(req))
    text = "".join(c.text or "" for c in chunks)
    assert text == "Hello"
    assert chunks[-1].done is True
    assert chunks[-1].usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_provider_accumulates_split_tool_arguments(monkeypatch) -> None:
    """Tool-call arguments arriving in pieces are joined before parsing."""
    mod = _load_provider()
    _fake_requests(monkeypatch, mod, [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"demo_ping","arguments":"{\\\"note\\\": \\\"he"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"llo\\\"}"}}]}}]}',
        "data: [DONE]",
    ])
    prov = mod.OpenAIProvider(_FakeKernel())
    tools = [ToolSpec(name="demo.ping", description="x")]
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=tools, model="m")
    chunks = list(prov.chat(req))
    calls = [c.tool_call for c in chunks if c.tool_call]
    assert len(calls) == 1
    assert calls[0].name == "demo.ping"  # wire name restored via _name_map
    assert calls[0].arguments == {"note": "hello"}
    assert calls[0].id == "call_1"


def test_provider_usage_on_legacy_chunk_tolerated(monkeypatch) -> None:
    mod = _load_provider()

    class OldChunk:
        def __init__(self, text=None, tool_call=None, reasoning=None, done=False):
            self.text = text
            self.tool_call = tool_call
            self.reasoning = reasoning
            self.done = done

    monkeypatch.setattr(mod, "ChatChunk", OldChunk)
    _fake_requests(monkeypatch, mod, [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "data: [DONE]",
    ])
    prov = mod.OpenAIProvider(_FakeKernel())
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=[], model="m")
    chunks = list(prov.chat(req))  # must not raise
    assert chunks[-1].done is True


def test_provider_nonstream_fallback(monkeypatch) -> None:
    """stream=false still works through the JSON path."""
    mod = _load_provider()

    class CfgNoStream(_Cfg):
        def get(self, k, d=""):
            if k == "provider-openai.stream":
                return "false"
            return super().get(k, d)

    class FakeKernelNoStream:
        config = CfgNoStream()

    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "hi", "tool_calls": []}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}

    class FakeRequests:
        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(mod, "requests", FakeRequests())
    prov = mod.OpenAIProvider(FakeKernelNoStream())
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=[], model="m")
    chunks = list(prov.chat(req))
    assert "".join(c.text or "" for c in chunks) == "hi"
    assert chunks[-1].usage == {"prompt_tokens": 2, "completion_tokens": 1}


def test_provider_warns_on_truncated_stream(monkeypatch) -> None:
    """An SSE stream that ends without [DONE] (upstream cut) is flagged as
    possibly truncated, and no done chunk is emitted so the kernel cache never
    stores a partial response."""
    mod = _load_provider()
    _fake_requests(monkeypatch, mod, [
        'data: {"choices":[{"delta":{"content":"part"}}]}',
        'data: {"choices":[{"delta":{"content":"ial"}}]}',
        # NOTE: no "data: [DONE]" - the connection just ended
    ])
    prov = mod.OpenAIProvider(_FakeKernel())
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=[], model="m")
    chunks = list(prov.chat(req))
    text = "".join(c.text or "" for c in chunks)
    assert "partial" in text
    assert "without [DONE]" in text
    assert chunks[-1].done is False  # truncated -> never cached