"""Tests for the log-stats plugin (request logging + token statistics)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.kernel import Kernel

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


def test_logger_service_registered(kernel: Kernel) -> None:
    assert "logger" in kernel._services


def test_chat_writes_log_entry(kernel: Kernel) -> None:
    kernel.chat("sess-log", "hello")  # provider has no key -> error text, still logged
    rows = kernel._services["logger"].read_rows()
    assert len(rows) >= 1
    row = rows[-1]
    assert row["session"] == "sess-log"
    assert "prompt_tokens" in row and "cache_hit" in row


def test_logger_stats_aggregates(kernel: Kernel) -> None:
    svc = kernel._services["logger"]
    svc.log_turn({"ts": 1, "session": "a", "model": "m", "prompt_tokens": 10, "completion_tokens": 5, "cache_hit": False, "rounds": 1, "tool_calls": 0})
    svc.log_turn({"ts": 2, "session": "b", "model": "m", "prompt_tokens": 0, "completion_tokens": 0, "cache_hit": True, "rounds": 1, "tool_calls": 0})
    s = svc.stats()
    assert s["requests"] == 2
    assert s["total_tokens"] == 15
    assert s["cache_hits"] == 1
    assert s["by_model"]["m"] == 15
