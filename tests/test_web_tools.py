"""Tests for the web-tools plugin (search parsing + fetch text extraction).

Network is mocked — no real requests are made.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jarvis.kernel import Kernel


@pytest.fixture
def tools(tmp_path: Path, monkeypatch) -> Kernel:
    monkeypatch.chdir(tmp_path)
    src = Path(__file__).resolve().parents[1] / "plugins" / "web-tools"
    plugins = tmp_path / "plugins"
    shutil.copytree(src, plugins / "web-tools")
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    k.load()
    return k


def _h(tools: Kernel, name: str):
    return tools._tools[name].handler


def _fake_requests(tools: Kernel, monkeypatch, body: str = "") -> None:
    """Replace the plugin module's requests with a stub returning `body`."""
    import sys

    mod = sys.modules["jarvis_plugin_web_tools"]

    class FakeResp:
        status_code = 200

        def __init__(self, text):
            self.text = text
            self.raw = type("R", (), {"read": lambda self, n=-1: text.encode("utf-8")})()

    class FakeRequests:
        def get(self, url, **kw):
            return FakeResp(body)

    monkeypatch.setattr(mod, "requests", FakeRequests())


DDG_HTML = """
<html><body>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example Title</a>
<a class="result__snippet">Some snippet text here</a>
<a class="result__a" href="https://second.example.org/x">Second Result</a>
</body></html>
"""


def test_web_search_parses_ddg_results(tools: Kernel, monkeypatch) -> None:
    _fake_requests(tools, monkeypatch, DDG_HTML)
    out = _h(tools, "web.search")("jarvis ai")
    assert "Example Title" in out
    assert "https://example.com/page" in out  # DDG redirect unwrapped
    assert "Some snippet text here" in out
    assert "Second Result" in out


def test_web_fetch_extracts_text(tools: Kernel, monkeypatch) -> None:
    _fake_requests(
        tools,
        monkeypatch,
        "<html><head><style>.x{}</style></head><body><h1>Hello</h1><p>World <b>bold</b></p></body></html>",
    )
    out = _h(tools, "web.fetch")("https://example.com")
    assert "Hello" in out
    assert "World bold" in out
    assert "<style>" not in out and "<h1>" not in out


def test_web_fetch_rejects_non_http(tools: Kernel, monkeypatch) -> None:
    _fake_requests(tools, monkeypatch, "x")
    out = _h(tools, "web.fetch")("file:///etc/passwd")
    assert "only http(s)" in out


def test_web_search_empty_query(tools: Kernel, monkeypatch) -> None:
    _fake_requests(tools, monkeypatch, DDG_HTML)
    out = _h(tools, "web.search")("   ")
    assert "empty" in out
