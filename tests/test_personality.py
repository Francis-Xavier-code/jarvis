"""Tests for the personality plugin + layered context injection."""
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

def test_personality_service_registered(kernel: Kernel) -> None:
    assert "personality" in kernel._services
    prompt = kernel._services["personality"].system_prompt()
    assert "Style:" in prompt
    assert "You are JARVIS" in prompt


def test_personality_injected_before_self(kernel: Kernel) -> None:
    """Context prefix order: personality -> self -> facts -> history."""
    seen = {}

    class Spy:
        kind = "provider"

        def chat(self, req):
            seen["sys"] = [m.content for m in req.messages if m.role == "system"]
            seen["n"] = len(req.messages)
            yield ChatChunk(text="ok")

    kernel._provider_svc = Spy()
    kernel.chat("sess-p", "hi")
    assert len(seen["sys"]) >= 2  # personality + self
    assert "Style:" in seen["sys"][0]  # personality first
    assert "Kernel: microkernel v1" in seen["sys"][1]  # self second
