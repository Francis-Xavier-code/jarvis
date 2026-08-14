"""Tests for cross-session facts memory (mem.* tools + context injection)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.kernel import Kernel
from jarvis.types import ChatChunk

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def kernel(monkeypatch, tmp_path: Path) -> Kernel:
    monkeypatch.setenv("JARVIS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_CONFIG", "/dev/null")
    monkeypatch.chdir(PROJECT)
    k = Kernel(plugins_dir=str(PROJECT / "plugins"), data_dir=str(tmp_path / "data"))
    k.load()
    assert not k.manager._load_errors, k.manager._load_errors
    return k

def test_memory_facts_tools_and_injection(kernel: Kernel) -> None:
    for name in ("mem.store", "mem.recall", "mem.forget"):
        assert name in kernel._tools

    kernel._tools["mem.store"].handler("user_language", "Chinese")
    seen = {}

    class Spy:
        kind = "provider"

        def chat(self, req):
            seen["sys"] = [m.content for m in req.messages if m.role == "system"]
            yield ChatChunk(text="ok")

    kernel._provider_svc = Spy()
    kernel.chat("sess-m", "hi")
    joined = "\n".join(seen["sys"])
    assert "user_language" in joined and "Chinese" in joined

    assert "user_language" in kernel._tools["mem.recall"].handler()
    kernel._tools["mem.forget"].handler("user_language")
    assert "no fact" in kernel._tools["mem.recall"].handler("user_language")


def test_facts_persist_across_sessions(kernel: Kernel) -> None:
    kernel._tools["mem.store"].handler("city", "Shanghai")
    # a second kernel instance (same data dir) still recalls the fact
    k2 = Kernel(plugins_dir=str(PROJECT / "plugins"), data_dir=kernel.data_dir)
    k2.load()
    out = k2._tools["mem.recall"].handler()
    assert "city: Shanghai" in out

def test_memory_load_dedups_consecutive_duplicates(kernel: Kernel) -> None:
    """Consecutive duplicate messages (double-submitted input) collapse to one."""
    from jarvis.types import ChatMessage

    mem = kernel._memory_svc
    mem.append("sess-dd", ChatMessage(role="user", content="hi"))
    mem.append("sess-dd", ChatMessage(role="user", content="hi"))  # duplicate
    mem.append("sess-dd", ChatMessage(role="assistant", content="ok"))
    loaded = mem.load("sess-dd")
    assert [m.content for m in loaded] == ["hi", "ok"]


def test_memory_load_keeps_same_text_from_different_tools(kernel: Kernel) -> None:
    """Two different tools returning identical text must NOT be deduped."""
    from jarvis.types import ChatMessage

    mem = kernel._memory_svc
    mem.append("sess-tt", ChatMessage(role="user", content="go"))
    mem.append("sess-tt", ChatMessage(role="tool", content="exit 0", name="bash.execute"))
    mem.append("sess-tt", ChatMessage(role="tool", content="exit 0", name="fs.read"))
    loaded = mem.load("sess-tt")
    assert [m.name for m in loaded if m.role == "tool"] == ["bash.execute", "fs.read"]

