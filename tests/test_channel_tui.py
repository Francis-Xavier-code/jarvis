"""Tests for the channel-tui plugin (textual TUI channel).

The app itself needs a TTY, so tests cover service registration, graceful
degradation without textual, and the confirm-bridge contract.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jarvis.kernel import Kernel


@pytest.fixture
def kernel(tmp_path: Path, monkeypatch) -> Kernel:
    monkeypatch.chdir(tmp_path)
    src = Path(__file__).resolve().parents[1] / "plugins" / "channel-tui"
    plugins = tmp_path / "plugins"
    shutil.copytree(src, plugins / "channel-tui")
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    k.load()
    return k


def test_tui_channel_registered(kernel: Kernel) -> None:
    assert any(getattr(c, "kind", "") == "tui" for c in kernel._channels)


def test_tui_degrades_without_textual(kernel: Kernel, monkeypatch, capsys) -> None:
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    monkeypatch.setattr(mod, "_TEXTUAL_OK", False)
    chan = next(c for c in kernel._channels if getattr(c, "kind", "") == "tui")
    chan.run(kernel)  # must not raise; prints install hint
    captured = capsys.readouterr()
    assert "textual" in captured.out


def test_app_constructs_with_textual(kernel: Kernel) -> None:
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    if not mod._TEXTUAL_OK:
        pytest.skip("textual not installed")
    app = mod._JarvisApp(kernel)
    assert app is not None
    assert app._kernel is kernel

def test_spinner_helpers_present(kernel: Kernel) -> None:
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    assert mod._SPINNER  # non-empty spinner frames
    app = mod._JarvisApp(kernel)
    for attr in ("_start_spinner", "_tick_spinner", "_stop_spinner"):
        assert hasattr(app, attr)

def test_md_inline_renders_and_escapes_brackets(kernel: Kernel) -> None:
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    # bold + code
    out = mod._md_inline("use **bold** and `code` here")
    assert "[bold]" in out and "code" in out
    # literal brackets survive (escaped for Rich, not eaten as tags)
    out2 = mod._md_inline("index arr[0] and [1, 2]")
    assert "arr[0]" in out2.replace("\\[", "[")
    # links become underlined labels
    out3 = mod._md_inline("[docs](https://x.dev)")
    assert "[underline]docs[/]" in out3
    assert "https://" not in out3


