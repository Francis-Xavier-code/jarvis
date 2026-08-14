"""channel-terminal: a minimal REPL channel.

Registers a 'channel' service; the kernel's ``chat`` subcommand calls
``channel.run(kernel)``. Also demonstrates hot-reload: edit this file (or its
mtime) and the manager reloads it without restarting the process.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from jarvis.types import KernelApi

# render.py lives next to this file. Plugins are imported under a dynamic
# module name (jarvis_plugin_<dir>), so a plain relative import fails; load
# it explicitly from the sibling path.
def _load_render():
    here = Path(__file__).resolve().parent / "render.py"
    spec = importlib.util.spec_from_file_location("_jarvis_terminal_render", here)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_render = _load_render()
render_md = _render.render_md


def setup(kernel: KernelApi) -> None:
    kernel.service("channel", _TerminalChannel())


def teardown(kernel: KernelApi) -> None:
    pass


class _TerminalChannel:
    kind = "terminal"

    def run(self, kernel) -> None:
        session = "terminal"
        print("JARVIS (terminal channel). Type 'exit' to quit.")
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line in ("exit", "quit"):
                break
            if not line:
                continue
            print("jarvis>", render_md(kernel.chat(session, line)))
