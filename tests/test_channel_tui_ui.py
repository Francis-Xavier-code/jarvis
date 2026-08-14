"""Tests for the dsh-TUI 1:1 visual kit (whale, big font, shimmer, design system)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_UI_DIR = Path(__file__).resolve().parents[1] / "plugins" / "channel-tui"


@pytest.fixture(scope="module")
def ui():
    root = str(_UI_DIR / "ui.py")
    spec = importlib.util.spec_from_file_location("channel_tui_ui_test", root)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.modules["bigfont_data"] = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("bigfont_data_test", str(_UI_DIR / "bigfont_data.py"))
    )
    sys.modules["whale_data"] = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("whale_data_test", str(_UI_DIR / "whale_data.py"))
    )
    importlib.util.spec_from_file_location("whale_data_test", str(_UI_DIR / "whale_data.py")).loader.exec_module(sys.modules["whale_data"])
    importlib.util.spec_from_file_location("bigfont_data_test", str(_UI_DIR / "bigfont_data.py")).loader.exec_module(sys.modules["bigfont_data"])
    spec.loader.exec_module(mod)
    return mod


def test_whale_renders_13_rows(ui) -> None:
    rows = ui.render_whale("standard")
    assert len(rows) == 13
    assert any("\u2580" in r for r in rows)  # half-block glyphs


def test_whale_has_13_frames(ui) -> None:
    seq = ui.whale_frames_sequence()
    assert len(seq) == 14  # standard..tail3..standard


def test_big_font_renders_javis(ui) -> None:
    rows = ui.render_big("JARVIS")
    assert len(rows) == 5
    assert len(rows[0].split()) >= 6  # J A R V I S columns


def test_design_system(ui) -> None:
    d = ui.divider("Title", color="#7c5cff")
    assert "Title" in d and "#7c5cff" in d
    pb = ui.progress_bar(0.42, 20)
    assert "\u2588" in pb  # block fill
    assert "+" in ui.status_icon("success")
    by = ui.byline("a", "b")
    assert "\u00b7" in by


def test_shimmer_changes_with_step(ui) -> None:
    s1 = ui.shimmer_line("JARVIS TUI", 0)
    s2 = ui.shimmer_line("JARVIS TUI", 5)
    assert s1 != s2

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 04:48:02 ---
