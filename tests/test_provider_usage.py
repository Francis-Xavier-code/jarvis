"""Tests that the provider threads token usage onto the done chunk.

The provider must tolerate kernels whose ChatChunk lacks a usage field
(core types do not hot-reload), so usage is attached defensively.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from jarvis.types import ChatMessage, ChatRequest


def _load_provider():
    root = Path(__file__).resolve().parents[1] / "plugins" / "provider-openai" / "plugin.py"
    spec = importlib.util.spec_from_file_location("provider_openai_usage_test", root)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_provider_threads_usage_onto_done_chunk(monkeypatch) -> None:
    mod = _load_provider()

    class Cfg:
        def get(self, k, d=""):
            if k == "provider-openai.openai_api_key":
                return "sk-test"
            if k == "provider-openai.openai_base_url":
                return "https://example.com/v1"
            return d

    class FakeKernel:
        config = Cfg()

    prov = mod.OpenAIProvider(FakeKernel())

    class FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    class FakeRequests:
        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(mod, "requests", FakeRequests())
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=[], model="m")
    chunks = list(prov.chat(req))
    assert chunks[-1].done is True
    assert chunks[-1].usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_provider_no_usage_field_is_tolerated(monkeypatch) -> None:
    """A legacy ChatChunk without usage must not crash the provider."""
    mod = _load_provider()

    class OldChunk:
        def __init__(self, text=None, tool_call=None, reasoning=None, done=False):
            self.text = text
            self.tool_call = tool_call
            self.reasoning = reasoning
            self.done = done

    monkeypatch.setattr(mod, "ChatChunk", OldChunk)

    class Cfg:
        def get(self, k, d=""):
            if k == "provider-openai.openai_api_key":
                return "sk-test"
            if k == "provider-openai.openai_base_url":
                return "https://example.com/v1"
            return d

    class FakeKernel:
        config = Cfg()

    prov = mod.OpenAIProvider(FakeKernel())

    class FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    class FakeRequests:
        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(mod, "requests", FakeRequests())
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")], tools=[], model="m")
    chunks = list(prov.chat(req))  # must not raise
    assert chunks[-1].done is True
