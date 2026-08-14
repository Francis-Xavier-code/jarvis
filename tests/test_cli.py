"""CLI tests: jarvis doctor and jarvis stats."""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from jarvis.main import cli

PROJECT = Path(__file__).resolve().parents[1]


def test_doctor_health_check(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_DATA", str(tmp_path / "data"))
    monkeypatch.chdir(PROJECT)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert "[ok]" in result.output or "[!!]" in result.output
    assert "plugins loaded" in result.output


def test_stats_empty_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_DATA", str(tmp_path / "data"))
    monkeypatch.chdir(PROJECT)
    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])
    assert "no requests" in result.output
