"""channel-tui: a full-screen TUI channel built on textual.

Separates output (scrollable panel) from input (single-line box), so typing
while JARVIS streams never interleaves with the reply. Features:
  * streamed assistant text in an output panel (auto-scroll)
  * tool calls and completions shown inline (check / cross + duration)
  * confirmation prompts rendered as a modal dialog (y/N buttons)
  * single-line input with up/down history and backslash continuation
  * busy state shown in the header; input typed while busy is queued

Requires the optional dependency textual (`uv pip install -e ".[ui]"`).
Soft-imported: without textual the plugin loads but reports on run.
Run with: `jarvis tui`
"""
from __future__ import annotations

import queue
import threading

from jarvis.types import KernelApi

# ---- soft dependency ----
try:
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header, Input, RichLog
    _TEXTUAL_OK = True
except ImportError:  # pragma: no cover
    _TEXTUAL_OK = False

_GREEN = "[#33ff57]"
_YELLOW = "[#ffd700]"
_DIM = "[dim]"
_CYAN = "[#00d7ff]"


def setup(kernel: KernelApi) -> None:
    kernel.service("channel", _TuiChannel())


def teardown(kernel: KernelApi) -> None:
    pass


class _JarvisApp(App):
    """Textual app: output panel + input box + header/footer."""

    CSS = """
    #out {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        margin: 0 1;
    }
    #in {
        dock: bottom;
        height: 3;
        margin: 0 1 1 1;
        border: tall $accent;
    }
    .confirm-prompt {
        padding: 1 2;
    }
    """

    BINDINGS = [
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear output"),
    ]

    def __init__(self, kernel) -> None:
        super().__init__()
        self._kernel = kernel
        self._busy = False
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._history: list[str] = []
        self._hist_idx: "int | None" = None
        self._partial = ""
        self._pending_confirm: "tuple[str, threading.Event, list[bool]] | None" = None

    # ---- UI wiring ----
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="out", wrap=True, markup=True, highlight=True)
        yield Input(id="in", placeholder="message JARVIS... (\\ continues a line, /help for commands)")
        yield Footer()

    def on_mount(self) -> None:
        self._kernel.confirm_action = self._confirm_wait
        self._write(f"{_GREEN}JARVIS TUI ready. Type /help for commands.[/]")
        self._focus_input()

    def _write(self, text: str) -> None:
        self.query_one("#out", RichLog).write(text)

    def _focus_input(self) -> None:
        self.query_one("#in", Input).focus()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.query_one(Header).sub_title = "busy..." if busy else "ready"

    # ---- confirm bridge (worker thread <-> UI, answered in the input row) ----
    def _confirm_wait(self, prompt: str) -> bool:
        """Called from the chat worker thread; blocks until the user answers.

        The prompt is shown at the bottom (output line + input placeholder) and
        answered with y/N directly on the keyboard - no popup over the output.
        """
        result: list[bool] = []
        done = threading.Event()
        self.call_from_thread(self._show_confirm, prompt, done, result)
        done.wait(timeout=180)
        return result[0] if result else False

    def _show_confirm(self, prompt: str, done: threading.Event, result: list[bool]) -> None:
        self._pending_confirm = (prompt, done, result)
        self._write(f"{_YELLOW}? {prompt} [y/N] (press y or n)[/]")
        self.query_one("#in", Input).placeholder = "answer y or n"
        self._focus_input()

    def _answer_confirm(self, ans: bool) -> None:
        if self._pending_confirm is None:
            return
        _prompt, done, result = self._pending_confirm
        self._pending_confirm = None
        self.query_one("#in", Input).placeholder = "message JARVIS... (\\ continues a line, /help for commands)"
        result.append(ans)
        done.set()
        self._write(f"{_DIM}↳ {'yes' if ans else 'no'}[/]")

    # ---- input handling ----
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.rstrip("\\").strip()
        self.query_one("#in", Input).value = ""
        if not text:
            return
        self._history.append(text)
        self._hist_idx = None
        if text.startswith("/"):
            self._handle_command(text)
            return
        if self._busy:
            self._queue.put(text)
            self._write(f"{_DIM}queued (JARVIS busy): {text}[/]")
            return
        self._start_chat(text)

    def on_input_key(self, event) -> None:
        """y/N answers the pending confirmation; Up/Down browse history."""
        if self._pending_confirm is not None:
            key = getattr(event, "key", "")
            if key in ("y", "Y"):
                self._answer_confirm(True)
                event.stop()
            elif key in ("n", "N", "escape"):
                self._answer_confirm(False)
                event.stop()
            return
        if self._busy:
            return
        inp = self.query_one("#in", Input)
        if event.key == "up":
            if self._history:
                if self._hist_idx is None:
                    self._hist_idx = len(self._history) - 1
                    self._partial = inp.value
                else:
                    self._hist_idx = max(0, self._hist_idx - 1)
                inp.value = self._history[self._hist_idx]
                event.stop()
        elif event.key == "down":
            if self._hist_idx is not None:
                self._hist_idx += 1
                if self._hist_idx >= len(self._history):
                    self._hist_idx = None
                    inp.value = self._partial
                else:
                    inp.value = self._history[self._hist_idx]
                event.stop()

    def _handle_command(self, cmd: str) -> None:
        c = cmd.strip()
        if c == "/help":
            self._write(_HELP)
        elif c in ("/exit", "/quit"):
            self.exit()
        elif c == "/clear":
            self.query_one("#out", RichLog).clear()
        else:
            self._write(f"{_DIM}unknown command: {c} (try /help)[/]")

    # ---- chat worker ----
    def _start_chat(self, text: str) -> None:
        self._set_busy(True)
        self._write(f"{_CYAN}you> {text}[/]")

        def work() -> None:
            try:
                self._kernel.chat(
                    "terminal",
                    text,
                    on_chunk=self._on_chunk,
                    on_tool=self._on_tool,
                    on_tool_done=self._on_tool_done,
                )
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._write, f"{_YELLOW}[error] {exc}[/]")
            finally:
                self.call_from_thread(self._finish_turn)

        threading.Thread(target=work, daemon=True).start()

    def _on_chunk(self, chunk) -> None:
        if chunk.text:
            self.call_from_thread(self._write, chunk.text)

    def _on_tool(self, call) -> None:
        args = ", ".join(f"{k}={v!r}" for k, v in list(call.arguments.items())[:4])
        self.call_from_thread(self._write, f"{_YELLOW}tool: {call.name}({args})[/]")

    def _on_tool_done(self, call, result: str, duration: float) -> None:
        summary = (result or "").strip().split("\n", 1)[0][:80]
        denied = "not confirmed" in result or result.startswith("[error]") or "refused" in result
        mark = "x" if denied else "ok"
        color = _DIM if denied else _GREEN
        self.call_from_thread(self._write, f"{color} {mark} {call.name} -> {summary} ({duration:.1f}s)[/]")

    def _finish_turn(self) -> None:
        self._set_busy(False)
        if not self._queue.empty():
            nxt = self._queue.get_nowait()
            self._start_chat(nxt)
        else:
            self._focus_input()

    def action_clear(self) -> None:
        self.query_one("#out", RichLog).clear()


_HELP = """
[bold cyan]Commands[/]
  /help /clear /exit

[bold cyan]Input[/]
  - end a line with backslash to continue on the next line
  - up/down arrows browse history
  - typing while JARVIS is busy queues your message
  - tool confirmations appear as a dialog: press the Yes/No button
  - ctrl+d quits, ctrl+l clears the output panel
"""


class _TuiChannel:
    kind = "tui"

    def run(self, kernel) -> None:
        if not _TEXTUAL_OK:
            print("[channel-tui] textual not installed - run: uv pip install -e .[ui]")
            return
        _JarvisApp(kernel).run()
