"""channel-terminal: a minimal REPL channel.

Registers a 'channel' service; the kernel's ``chat`` subcommand calls
``channel.run(kernel)``. Also demonstrates hot-reload: edit this file (or its
mtime) and the manager reloads it without restarting the process.
"""
from __future__ import annotations

from jarvis.types import KernelApi


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
            print("jarvis>", kernel.chat(session, line))
