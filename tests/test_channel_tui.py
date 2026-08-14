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


def test_app_mounts_headless(kernel: Kernel) -> None:
    """Mount the real app: on_mount builds the brand markup, pushes the splash
    screen and registers confirm handling.

    Regression: the brand tagline wrapped _DIM in an extra bracket pair
    ("[[dim]]"), which Rich parses as a literal "[" - the trailing "[/]" then
    had no open tag and startup raised MarkupError. Mounting the app headlessly
    exercises exactly that path (on_mount -> Static.update -> visualize).
    """
    import asyncio
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    if not mod._TEXTUAL_OK:
        pytest.skip("textual not installed")

    async def _mount() -> None:
        app = mod._JarvisApp(kernel)
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            brand = app.query_one("#brand", mod.Static)
            content = brand.render()
            # big-font logo rows + tagline are present, and the tagline carries
            # the dim style (i.e. the markup parsed, it was not literal [[dim]])
            assert "microkernel · everything is a plugin" in content.plain
            assert "dim" in str(content.spans)
            app.exit()

    asyncio.run(_mount())


def test_tool_label_truncates_long_args(kernel: Kernel) -> None:
    """Tool labels never exceed one line: per-arg and overall caps."""
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    label = mod._tool_label("bash.execute", {"command": "echo " + "x" * 300, "cwd": ""})
    assert len(label) <= 110
    assert "..." in label  # the truncated arg value carries the ellipsis
    short = mod._tool_label("web.search", {"query": "hi"})
    assert short == "WebSearch(query='hi')"


def test_streamed_partial_line_renders_live(kernel: Kernel) -> None:
    """Streamed text is visible before a newline arrives (regression: the
    in-flight line used to be hidden until the turn ended)."""
    import asyncio
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    if not mod._TEXTUAL_OK:
        pytest.skip("textual not installed")

    async def _run() -> None:
        app = mod._JarvisApp(kernel)
        async with app.run_test() as pilot:
            app._stream_md("hel")
            app._stream_md("lo wo")
            await pilot.pause(0.1)
            chat = app.query_one("#chat")
            plains = [w.render().plain for w in chat.query(mod.Static)]
            assert any("hello wo" in p for p in plains), plains
            app.exit()

    asyncio.run(_run())


def test_tool_messages_display_via_thread_bridge(kernel: Kernel) -> None:
    """Tool call/result callbacks arrive from the worker thread and must
    render through the call_from_thread bridge (regression: direct DOM
    mutation from the worker thread could drop/glitch tool messages)."""
    import asyncio
    import sys
    import threading

    from jarvis.types import ToolCall

    mod = sys.modules["jarvis_plugin_channel_tui"]
    if not mod._TEXTUAL_OK:
        pytest.skip("textual not installed")

    async def _run() -> None:
        app = mod._JarvisApp(kernel)
        async with app.run_test() as pilot:
            call = ToolCall(name="bash.execute", arguments={"command": "echo " + "y" * 300})

            def poke() -> None:
                app._on_tool(call)
                app._on_tool_done(call, "ok\n" + "z" * 200, 1.5)

            threading.Thread(target=poke).start()
            await pilot.pause(0.4)
            chat = app.query_one("#chat")
            plains = [w.render().plain for w in chat.query(mod.Static)]
            assert any("Bash" in p and "->" in p and "ok" in p for p in plains), plains
            app.exit()

    asyncio.run(_run())

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


def test_autoapprove_command_toggles_kernel(kernel: Kernel) -> None:
    """/autoapprove flips the live kernel gate (no config svc in this fixture)."""
    import sys

    mod = sys.modules["jarvis_plugin_channel_tui"]
    app = mod._JarvisApp(kernel)
    # query shows the current state without changing it
    assert "OFF" in app._autoapprove_cmd("/autoapprove")
    assert kernel.auto_approve() is False
    # on / off / toggle
    assert "ON" in app._autoapprove_cmd("/autoapprove on")
    assert kernel.auto_approve() is True
    assert "OFF" in app._autoapprove_cmd("/autoapprove toggle")
    assert kernel.auto_approve() is False
    assert "OFF" in app._autoapprove_cmd("/autoapprove off")
    assert kernel.auto_approve() is False
    assert "ON" in app._autoapprove_cmd("/autoapprove yes")
    assert kernel.auto_approve() is True
    # unknown argument -> usage hint, state untouched
    assert "usage" in app._autoapprove_cmd("/autoapprove maybe")
    assert kernel.auto_approve() is True


