"""Tests for the cache-core plugin (transparent LLM response cache).

Unit tests exercise the cache service directly (fingerprint, TTL, LRU,
error-suppression); the kernel integration (get/put wired into the agent
loop) lives in test_kernel.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from jarvis.types import ChatChunk, ChatMessage, ChatRequest


@pytest.fixture(scope="module")
def cache_mod():
    root = Path(__file__).resolve().parents[1] / "plugins" / "cache-core" / "plugin.py"
    spec = importlib.util.spec_from_file_location("cache_core_under_test", root)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _req(model: str = "m", content: str = "hi") -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role="user", content=content)],
        tools=[],
        model=model,
    )


def _ok(text: str) -> list[ChatChunk]:
    return [ChatChunk(text=text), ChatChunk(done=True)]


def test_miss_then_hit(cache_mod) -> None:
    svc = cache_mod._CacheService(None)
    req = _req()
    assert svc.get(req) is None
    svc.put(req, _ok("hello"))
    got = svc.get(req)
    assert got is not None
    assert got[0].text == "hello"
    assert got is not _ok("hello")  # deep-copied, not shared mutable state


def test_fingerprint_distinguishes_model(cache_mod) -> None:
    svc = cache_mod._CacheService(None)
    svc.put(_req(model="a"), _ok("x"))
    assert svc.get(_req(model="b")) is None


def test_fingerprint_distinguishes_messages(cache_mod) -> None:
    svc = cache_mod._CacheService(None)
    svc.put(_req(content="one"), _ok("x"))
    assert svc.get(_req(content="two")) is None


def test_error_response_not_cached(cache_mod) -> None:
    """A provider error stub (no done=True) must never be cached."""
    svc = cache_mod._CacheService(None)
    req = _req()
    svc.put(req, [ChatChunk(text="[provider-openai] no API key")])
    assert svc.get(req) is None


def test_ttl_expiry(cache_mod) -> None:
    svc = cache_mod._CacheService(None, ttl_seconds=-1)  # already expired
    req = _req()
    svc.put(req, _ok("x"))
    assert svc.get(req) is None


def test_lru_eviction(cache_mod) -> None:
    svc = cache_mod._CacheService(None, max_entries=1)
    svc.put(_req(model="a"), _ok("a"))
    svc.put(_req(model="b"), _ok("b"))
    assert svc.get(_req(model="a")) is None  # evicted (LRU)
    assert svc.get(_req(model="b")) is not None


def test_disabled_never_caches(cache_mod) -> None:
    svc = cache_mod._CacheService(None, enabled=False)
    req = _req()
    svc.put(req, _ok("x"))
    assert svc.get(req) is None


def test_stats(cache_mod) -> None:
    svc = cache_mod._CacheService(None)
    svc.get(_req())  # miss
    svc.put(_req(), _ok("x"))
    svc.get(_req())  # hit
    st = svc.stats()
    assert st["hits"] == 1
    assert st["misses"] == 1
    assert st["hit_rate"] == 0.5
    assert st["entries"] == 1
