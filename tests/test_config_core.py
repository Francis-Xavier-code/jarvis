"""Tests for the config-core plugin's persistence (set -> config.toml).

The config plugin holds config.toml and exposes get/snapshot; ``set`` writes a
single top-level key back to the file, preserving comments and section order —
that is what the TUI's /autoapprove toggle relies on to survive restarts.
"""
from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def config_core(tmp_path: Path, monkeypatch):
    """Load the real config-core plugin with config.toml pointed at tmp_path."""
    monkeypatch.setenv("JARVIS_CONFIG", str(tmp_path / "config.toml"))
    plugin_root = Path(__file__).resolve().parents[1] / "plugins" / "config-core"
    spec = importlib.util.spec_from_file_location(
        "config_core_under_test", plugin_root / "plugin.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod, tmp_path / "config.toml"


def test_set_creates_missing_file(config_core) -> None:
    mod, cfg = config_core
    mod._ConfigService({}).set("auto_approve", True)
    assert cfg.exists()
    assert cfg.read_text(encoding="utf-8") == "auto_approve = true\n"
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["auto_approve"] is True


def test_set_inserts_key_before_sections_preserving_comments(config_core) -> None:
    mod, cfg = config_core
    cfg.write_text(
        "# keep me\n\n"
        "[provider-openai]\n"
        'openai_base_url = "https://example.com"\n'
        "model = \"m\"\n",
        encoding="utf-8",
    )
    mod._ConfigService({}).set("auto_approve", True)
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("# keep me\n\nauto_approve = true\n[provider-openai]")
    assert "openai_base_url" in text
    assert tomllib.loads(text)["auto_approve"] is True


def test_set_replaces_existing_key_in_place(config_core) -> None:
    mod, cfg = config_core
    cfg.write_text(
        "auto_approve = false\n\n[provider-openai]\nmodel = \"m\"\n",
        encoding="utf-8",
    )
    svc = mod._ConfigService({})
    svc.set("auto_approve", True)
    svc.set("auto_approve", False)
    text = cfg.read_text(encoding="utf-8")
    assert text.count("auto_approve") == 1
    assert "auto_approve = false" in text
    assert tomllib.loads(text)["auto_approve"] is False


def test_set_updates_in_memory_data(config_core) -> None:
    mod, cfg = config_core
    svc = mod._ConfigService({"model": "m"})
    svc.set("auto_approve", True)
    assert svc.get("auto_approve") is True
    assert svc.snapshot()["model"] == "m"


def test_set_escapes_strings(config_core) -> None:
    mod, cfg = config_core
    svc = mod._ConfigService({})
    svc.set("greeting", 'say "hi" \\ ok')
    assert 'greeting = "say \\"hi\\" \\\\ ok"' in cfg.read_text(encoding="utf-8")
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["greeting"] == 'say "hi" \\ ok'
