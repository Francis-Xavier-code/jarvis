"""Tests for the terminal channel's Markdown -> ANSI renderer."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_RENDER_PATH = Path(__file__).resolve().parents[1] / "plugins" / "channel-terminal" / "render.py"
_spec = importlib.util.spec_from_file_location("_term_render_test", _RENDER_PATH)
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)


def test_strips_inline_markers() -> None:
    out = render._render_block("这是 **粗体** 和 *斜体* 和 `代码`")
    assert "**" not in out
    assert "*斜体*" not in out
    assert "`代码`" not in out
    # text content preserved
    assert "粗体" in out and "斜体" in out and "代码" in out


def test_heading_rendered() -> None:
    out = render._render_block("# 标题")
    assert "##" not in out
    assert "标题" in out


def test_list_rendered() -> None:
    out = render._render_block("- a\n- b")
    assert "• a" in out
    assert "• b" in out


def test_code_block_rendered() -> None:
    out = render._render_block("```\nprint(1)\n```")
    assert "print(1)" in out
    assert "┌" in out or "│" in out  # code fence decoration


def test_ordered_list() -> None:
    out = render._render_block("1. 一\n2. 二")
    assert "1. 一" in out
    assert "2. 二" in out


def test_blockquote() -> None:
    out = render._render_block("> 引用")
    assert "引用" in out
    assert "│" in out


def test_link_stripped() -> None:
    out = render._render_block("见 [文档](http://x.com)")
    assert "http://x.com" not in out
    assert "文档" in out


def test_render_md_never_raises_on_plain_text() -> None:
    assert render.render_md("just text") == "just text"
    assert render.render_md("") == ""
