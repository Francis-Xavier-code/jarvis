"""Tests for the mdcat-render plugin.

Covers md.render / md.render_file tools and the render service, using a
fake mdcat binary so no Rust toolchain is required. Also verifies that
channel-terminal's buffered mode prefers a registered render service.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from jarvis.kernel import Kernel
from jarvis.types import KernelApi

_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN = _ROOT / "plugins" / "mdcat-render" / "plugin.py"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("mdcat_render_test", _PLUGIN)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


class _Cfg:
    def get(self, k, d=None):
        return d


class _CapturingKernel:
    """Minimal kernel stand-in: captures registered tools + services."""

    def __init__(self):
        self.config = _Cfg()
        self.config_api = _Cfg()  # KernelApi.config -> kernel.config_api
        self.tools = {}
        self.services = {}
        self._active_plugin = "mdcat-render"

    def _register_tool(self, spec):
        self.tools[spec.name] = spec.handler

    def _register_service(self, kind, impl, plugin):
        self.services[kind] = impl

    def _set_active(self, name):
        self._active_plugin = name


@pytest.fixture
def loaded(mod):
    kapi = KernelApi(_CapturingKernel())
    mod.setup(kapi)
    return kapi._kernel


@pytest.fixture
def fake_binary(tmp_path, monkeypatch, mod):
    """A fake `mdcat` that echoes stdin (or its file argument)."""
    binpath = tmp_path / "mdcat"
    binpath.write_text("#!/bin/sh\ncat \"$@\"\n")
    binpath.chmod(0o755)
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(binpath) if name == "mdcat" else None)
    return binpath


def test_tool_missing_binary_message(loaded, monkeypatch, mod):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    out = loaded.tools["md.render"]("**hi**")
    assert "binary not found" in out
    out2 = loaded.tools["md.render_file"]("x.md")
    assert "binary not found" in out2


def test_tool_renders_text_via_fake_binary(loaded, fake_binary):
    out = loaded.tools["md.render"]("**hi** and `code`")
    assert out == "**hi** and `code`"  # fake echoes stdin verbatim


def test_tool_renders_file_via_fake_binary(loaded, fake_binary, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# title\n\nbody", encoding="utf-8")
    out = loaded.tools["md.render_file"](str(f))
    assert "# title" in out and "body" in out


def test_tool_ansi_stripped_by_default(loaded, monkeypatch, mod, tmp_path):
    binpath = tmp_path / "mdcat"
    binpath.write_text("#!/bin/sh\nprintf \"\\033[31mred\\033[0m\\n\"\n")
    binpath.chmod(0o755)
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(binpath) if name == "mdcat" else None)
    plain = loaded.tools["md.render"]("x")
    assert plain == "red\n"
    raw = loaded.tools["md.render"]("x", ansi=True)
    assert "\x1b[" in raw


def test_service_falls_back_without_binary(loaded, monkeypatch, mod):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    svc = loaded.services["render"]
    assert svc.render("plain text") == "plain text"


def test_service_renders_with_binary(loaded, fake_binary):
    svc = loaded.services["render"]
    assert svc.render("hi") == "hi"


def test_terminal_channel_prefers_render_service(tmp_path) -> None:
    """channel-terminal buffered mode uses the render service when present."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    shutil.copytree(_ROOT / "plugins" / "channel-terminal", plugins / "channel-terminal")
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    k.load()
    mod2 = sys.modules["jarvis_plugin_channel_terminal"]
    # no render service yet -> built-in fallback (None = caller uses render_md)
    assert mod2._render_reply(k, "hello") is None

    class FakeSvc:
        def render(self, text):
            return "[R]" + text + "[/R]"

    k._services["render"] = FakeSvc()
    assert mod2._render_reply(k, "hello") == "[R]hello[/R]"

    # a broken renderer falls back instead of crashing chat
    class Broken:
        def render(self, text):
            raise RuntimeError("boom")

    k._services["render"] = Broken()
    assert mod2._render_reply(k, "hello") is None