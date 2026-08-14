"""channel-terminal: an interactive REPL channel (pi-agent style input).

Input experience:
  * readline line editing with persistent history (data/history.txt)
  * multi-line input: a line ending in "\" continues; pasted multi-line
    blocks are detected via a short stdin probe and sent as one message
  * /help and /exit commands; Ctrl-D exits; Ctrl-C interrupts the running
    turn (press again while idle to give up the line)

Output experience:
  * streaming by default: assistant text renders as it is generated and
    tool calls are announced inline. Set JARVIS_NO_STREAM=1 to fall back to
    the buffered Markdown->ANSI renderer (render.py) instead.
"""
from __future__ import annotations

import os
import sys

from jarvis.types import KernelApi

from .render import render_md

_BOLD = "\033[1m"
_DIM = "\033[2m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"

_USE_COLOR = (
    sys.stdout.isatty()
    and not os.environ.get("NO_COLOR")
    and os.environ.get("TERM", "dumb") != "dumb"
)

HELP = """\
Commands:
  exit / quit / Ctrl-D   leave JARVIS
  /help                  show this help
  /exit                  same as exit

Input:
  - end a line with \\ to continue on the next line
  - paste a multi-line block and it is sent as a single message
  - while JARVIS is replying, your keystrokes are queued: they become the
    NEXT message after the reply finishes (the current reply cannot see
    them). Press Ctrl-C to interrupt the current reply and start fresh.
"""


def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOR else text


def _setup_readline(data_dir: str) -> None:
    """Persistent readline history (up/down arrows)."""
    import atexit
    import readline

    hist = os.path.join(data_dir, "history.txt")
    try:
        os.makedirs(data_dir, exist_ok=True)
        readline.read_history_file(hist)
    except (OSError, FileNotFoundError):
        pass
    readline.set_history_length(1000)

    def _save() -> None:
        try:
            readline.write_history_file(hist)
        except OSError:
            pass

    atexit.register(_save)


def _pending_input(timeout: float = 0.08) -> bool:
    """True if stdin already has more data (pasted block continuation)."""
    try:
        import select

        return bool(select.select([sys.stdin], [], [], timeout)[0])
    except Exception:  # noqa: BLE001
        return False


def _read_message() -> str:
    """Read one user message, joining continuation lines and pasted blocks."""
    lines: list[str] = []
    while True:
        prompt = "you> " if not lines else "...> "
        line = input(prompt)
        if not lines and not line.strip():
            return ""
        if line.endswith("\\"):
            lines.append(line[:-1])
            continue
        lines.append(line)
        if _pending_input():
            continue  # more lines of a paste are coming
        break
    return "\n".join(lines)


def _handle_command(text: str) -> "str | None":
    """Handle /-commands. Returns "exit" to leave, "handled" when consumed,
    None when text is a normal message."""
    cmd = text.strip()
    if cmd == "/exit":
        return "exit"
    if cmd == "/help":
        print(HELP)
        return "handled"
    if cmd.startswith("/"):
        print(f"unknown command: {cmd} (try /help)")
        return "handled"
    return None


class _TerminalChannel:
    kind = "terminal"

    def __init__(self) -> None:
        self._segment = "text"  # current stream segment: "text" | "reasoning"
        self._started = False   # have we printed any content yet?

    def _stream_chunk(self, chunk) -> None:
        if os.environ.get("JARVIS_SHOW_REASONING") == "1":
            # Opt-in thinking chain. Reasoning precedes text in the stream:
            # emit in that order, on fresh lines per segment, "🧠" once per
            # segment, so chunks never glue together or interleave.
            for kind, content in (("reasoning", chunk.reasoning), ("text", chunk.text)):
                if not content:
                    continue
                if kind != self._segment:
                    if self._started:
                        print()
                    self._segment = kind
                    self._started = True
                if kind == "reasoning":
                    print(_c(_DIM, "🧠 " + content), end="", flush=True)
                else:
                    print(content, end="", flush=True)
        elif chunk.text:
            # Default: keep the thinking chain out of the terminal.
            print(chunk.text, end="", flush=True)

    def _stream_tool(self, call) -> None:
        args = ", ".join(f"{k}={v!r}" for k, v in list(call.arguments.items())[:5])
        print(_c(_YELLOW, f"\n⚙ {call.name}({args})"), flush=True)

    def run(self, kernel) -> None:
        session = "terminal"
        _setup_readline(kernel.data_dir)
        stream = os.environ.get("JARVIS_NO_STREAM", "") == ""
        print("JARVIS (terminal channel). Type 'exit' or Ctrl-D to quit. '/help' for help.")
        while True:
            try:
                text = _read_message()
            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                break
            if not text.strip():
                continue
            stripped = text.strip()
            if stripped in ("exit", "quit"):
                break
            if _handle_command(stripped) == "exit":
                break
            print()
            try:
                if stream:
                    print(_c(_DIM, "\u231b thinking\u2026 (Ctrl-C interrupts; your next input queues)"), flush=True)
                    reply = kernel.chat(
                        session, text, on_chunk=self._stream_chunk, on_tool=self._stream_tool
                    )
                    print()
                else:
                    print(_c(_DIM, "\u231b thinking\u2026"), flush=True)
                    reply = kernel.chat(session, text)
                    print()
                    print("jarvis>", render_md(reply))
            except KeyboardInterrupt:
                print("\n[jarvis] interrupted.")


def setup(kernel: KernelApi) -> None:
    kernel.service("channel", _TerminalChannel())


def teardown(kernel: KernelApi) -> None:
    pass

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 01:42:40 ---
