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
import re
import threading
import time

from jarvis.types import KernelApi

# ---- soft dependency ----
try:
    from textual.app import App, ComposeResult
    from textual.theme import Theme
    from textual.theme import Theme
    from textual.widgets import Footer, Header, Input, RichLog, Static
    _TEXTUAL_OK = True
except ImportError:  # pragma: no cover
    _TEXTUAL_OK = False

_PRIMARY = "[#7c5cff]"
_SECONDARY = "[#58a6ff]"
_GREEN = "[#3fb950]"
_ORANGE = "[#ff9e64]"
_DIM = "[dim]"
_SURFACE = "[on #161b22]"

# ---- streaming Markdown -> Rich markup ----
# RichLog(markup=True) understands [tags], not Markdown syntax, so we convert
# the assistant's streamed text line by line before writing it to the panel.

_INLINE_MD = [
    (re.compile(r"`([^`]+)`"), r"[#58a6ff]\1[/]"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"[bold]\1[/]"),
    (re.compile(r"__([^_]+)__"), r"[bold]\1[/]"),
    (re.compile(r"\*([^*]+)\*"), r"[italic]\1[/]"),
    (re.compile(r"_([^_]+)_"), r"[italic]\1[/]"),
    (re.compile(r"~~([^~]+)~~"), r"[dim]\1[/]"),
]


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _md_inline(text: str) -> str:
    """Convert inline markdown markers to Rich markup tags.

    Literal square brackets in the source are escaped to `\[` first (Rich
    parses `[...]` as tags), so text like `arr[0]` or `[1, 2]` survives.
    Links are stashed before escaping and re-expanded as underlined labels.
    """
    links: list[tuple[str, str]] = []

    def _stash(m) -> str:
        links.append((m.group(1), m.group(2)))
        return f"\x00LINK{len(links) - 1}\x00"

    text = _LINK_RE.sub(_stash, text)
    text = text.replace("[", "\\[")
    for pat, repl in _INLINE_MD:
        text = pat.sub(repl, text)
    for i, (label, _url) in enumerate(links):
        text = text.replace(f"\x00LINK{i}\x00", f"[underline]{_md_inline(label)}[/]")
    return text


def _md_block(line: str, in_code: bool) -> str:
    """Render one markdown line as Rich markup (block-level rules)."""
    if in_code:
        return f"{_SURFACE} | {line}[/]"
    stripped = line.strip()
    m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
    if m:
        return f"[bold #7c5cff]{'#' * len(m.group(1))} {_md_inline(m.group(2))}[/]"
    if re.match(r"^(\*{3,}|_{3,}|-{3,})\s*$", stripped):
        return "[dim]" + "-" * 40 + "[/]"
    if stripped.startswith(">"):
        return f"[dim]| {_md_inline(stripped.lstrip('> ').strip())}[/]"
    m = re.match(r"^(\s*)([-*+])\s+(.*)$", line)
    if m:
        indent = "  " * (len(m.group(1)) // 2)
        bullet = "[bold #3fb950]-[/]" if not m.group(1) else "[bold #3fb950]-[/]"
        return f"{indent}{bullet} {_md_inline(m.group(3))}"
    m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
    if m:
        indent = "  " * (len(m.group(1)) // 2)
        return f"{indent}[bold #3fb950]{m.group(2)}.[/] {_md_inline(m.group(3))}"
    return _md_inline(line)

# tool-call spinner frames (braille dots)
_SPINNER = "|/-\\"


def setup(kernel: KernelApi) -> None:
    kernel.service("channel", _TuiChannel())


def teardown(kernel: KernelApi) -> None:
    pass


_THEME = Theme(
    name="jarvis-dark",
    primary="#7c5cff",
    secondary="#58a6ff",
    accent="#ff9e64",
    foreground="#e6edf3",
    background="#0d1117",
    success="#3fb950",
    warning="#d29922",
    error="#f85149",
    surface="#161b22",
    panel="#0d1117",
    dark=True,
)


class _JarvisApp(App):
    """Textual app: output panel + input box + header/footer."""

    CSS = """
    Screen { background: $background; }
    #out {
        height: 1fr;
        margin: 0 1;
        padding: 0 1;
        background: $panel;
    }
    #status {
        height: 1;
        margin: 0 2;
        content-align: left middle;
        color: $primary;
    }
    #in {
        dock: bottom;
        height: 3;
        margin: 0 1 1 1;
        padding: 0 1;
        background: $surface;
        border: hkey $primary;
    }
    #in:focus {
        border: hkey $accent;
    }
    Header { background: $surface; color: $text; }
    Footer { background: $surface; }
    """

    BINDINGS = [
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear output"),
        ("up", "history_prev", "History prev"),
        ("down", "history_next", "History next"),
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
        self._md_part = ""   # incomplete md line being streamed
        self._in_code = False
        self._assistant_prefix = False  # whether "jarvis" marker was emitted
        self._spinner_text = ""
        self._spinner_frame = 0
        self._spinner_timer = None
        self._turn_start = 0.0

    # ---- UI wiring ----
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="out", wrap=True, markup=True, highlight=True)
        yield Static("", id="status")
        yield Input(id="in", placeholder="message JARVIS... (\\ continues a line, /help for commands)")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.register_theme(_THEME)
            self.theme = "jarvis-dark"
        except Exception:  # noqa: BLE001 - already registered / older textual
            pass
        self._kernel.confirm_action = self._confirm_wait
        self._write(f"{_PRIMARY}JARVIS >[/] ready. Type /help for commands.")
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
        self._write(f"{_ORANGE}? {prompt} [y/N] (press y or n)[/]")
        self.query_one("#in", Input).placeholder = "answer y or n"
        self.query_one("#status", Static).update(f"{_ORANGE}awaiting your y/N...[/]")
        self._focus_input()

    def _answer_confirm(self, ans: bool) -> None:
        if self._pending_confirm is None:
            return
        _prompt, done, result = self._pending_confirm
        self._pending_confirm = None
        self.query_one("#in", Input).placeholder = "message JARVIS... (\\ continues a line, /help for commands)"
        result.append(ans)
        done.set()
        self._write(f"{_DIM}-> {'yes' if ans else 'no'}[/]")

    # ---- input handling ----
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._pending_confirm is not None:
            v = event.value.strip().lower()
            if v in ("y", "yes"):
                self._answer_confirm(True)
            elif v in ("n", "no", ""):
                self._answer_confirm(False)
            self.query_one("#in", Input).value = ""
            return
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

    def on_key(self, event) -> None:
        """App-level: y/N answers a pending confirmation, regardless of focus."""
        if self._pending_confirm is not None and event.key in ("y", "Y", "n", "N", "escape"):
            self._answer_confirm(event.key.lower() in ("y",))
            self.query_one("#in", Input).value = ""
            event.stop()

    def action_history_prev(self) -> None:
        if self._busy or self._pending_confirm is not None or not self._history:
            return
        inp = self.query_one("#in", Input)
        if self._hist_idx is None:
            self._hist_idx = len(self._history) - 1
            self._partial = inp.value
        else:
            self._hist_idx = max(0, self._hist_idx - 1)
        inp.value = self._history[self._hist_idx]

    def action_history_next(self) -> None:
        if self._busy or self._pending_confirm is not None or self._hist_idx is None:
            return
        inp = self.query_one("#in", Input)
        self._hist_idx += 1
        if self._hist_idx >= len(self._history):
            self._hist_idx = None
            inp.value = self._partial
        else:
            inp.value = self._history[self._hist_idx]

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
        self._md_part = ""
        self._in_code = False
        self._assistant_prefix = False
        self._turn_start = time.time()
        self._write("")
        lines = text.split("\n")
        self._write(f"{_SECONDARY}you >[/] {lines[0]}")
        for extra in lines[1:]:
            self._write(f"  {extra}")
        # visible "thinking" animation while waiting for the first token
        self._start_spinner("thinking...")

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
                self.call_from_thread(self._write, f"{_ORANGE}[error] {exc}[/]")
            finally:
                self.call_from_thread(self._finish_turn)

        threading.Thread(target=work, daemon=True).start()

    # ---- tool-call spinner ----
    def _start_spinner(self, text: str) -> None:
        self._spinner_text = text
        self._spinner_frame = 0
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner)
        self._tick_spinner()

    def _tick_spinner(self) -> None:
        frame = _SPINNER[self._spinner_frame % len(_SPINNER)]
        self._spinner_frame += 1
        self.query_one("#status", Static).update(f"{_PRIMARY}{frame} {self._spinner_text}[/]")

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.query_one("#status", Static).update("")

    def _on_chunk(self, chunk) -> None:
        if chunk.text:
            # text arriving: drop the thinking/tool spinner (re-armed by _on_tool)
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(self._stream_md, chunk.text)

    # ---- streaming markdown -> rich markup ----
    def _stream_md(self, text: str) -> None:
        """Feed a streamed assistant chunk; render complete lines as md."""
        text = self._md_part + text
        lines = text.split("\n")
        self._md_part = lines.pop()
        for ln in lines:
            self._write(self._mark_first(self._md_line(ln)))

    def _md_line(self, ln: str) -> str:
        stripped = ln.strip()
        if stripped.startswith("```"):
            self._in_code = not self._in_code
            if self._in_code:
                return f"{_SURFACE} code [/]"
            return f"{_SURFACE} [/]"
        return _md_block(ln, self._in_code)

    def _flush_md(self) -> None:
        if self._md_part:
            self._write(self._mark_first(self._md_line(self._md_part)))
            self._md_part = ""
        self._in_code = False

    def _mark_first(self, rendered: str) -> str:
        """Prefix the first assistant line with a marker, then never again."""
        if not self._assistant_prefix:
            self._assistant_prefix = True
            return f"{_PRIMARY}jarvis >[/] {rendered}"
        return rendered

    def _on_tool(self, call) -> None:
        args = ", ".join(f"{k}={v!r}" for k, v in list(call.arguments.items())[:4])
        self.call_from_thread(self._write, f"{_DIM}  > {call.name}({args})[/]")
        self.call_from_thread(self._start_spinner, f"working: {call.name}({args})")

    def _on_tool_done(self, call, result: str, duration: float) -> None:
        summary = (result or "").strip().split("\n", 1)[0][:80]
        denied = "not confirmed" in result or result.startswith("[error]") or "refused" in result
        mark = "x" if denied else "+"
        color = _DIM if denied else _GREEN
        self.call_from_thread(self._write, f"{color}  {mark} {call.name} -> {summary} ({duration:.1f}s)[/]")
        self.call_from_thread(self._stop_spinner)

    def _finish_turn(self) -> None:
        self._flush_md()
        self._stop_spinner()
        self._set_busy(False)
        elapsed = time.time() - self._turn_start if self._turn_start else 0.0
        self._write("")
        self.query_one("#status", Static).update(f"{_GREEN}+ done ({elapsed:.1f}s)[/]")
        self.set_timer(1.2, self._clear_status)
        if not self._queue.empty():
            nxt = self._queue.get_nowait()
            self._start_chat(nxt)
        else:
            self._focus_input()

    def _clear_status(self) -> None:
        """Clear the transient completion status unless a new turn already owns it."""
        if not self._busy and self._spinner_timer is None:
            self.query_one("#status", Static).update("")

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

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 02:11:23 ---
