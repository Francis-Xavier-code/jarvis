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

from . import ui
from .ui import render_big, shimmer_line

# ---- soft dependency ----
try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.screen import Screen
    from textual.theme import Theme
    from textual.widgets import Footer, Header, Input, Static
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
    r"""Convert inline markdown markers to Rich markup tags.

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
        return f"{_SURFACE} | {_esc(line)}[/]"
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

# tool-call spinner frames (ASCII-safe)
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# display names for common tools (Claude Code style)
_KNOWN_TOOLS = {
    "bash.execute": "Bash",
    "fs.read": "Read", "fs.write": "Write", "fs.edit": "Edit", "fs.append": "Append",
    "fs.list": "List", "fs.glob": "Glob", "fs.undo": "Undo",
    "web.search": "WebSearch", "web.fetch": "WebFetch",
    "mem.store": "MemStore", "mem.recall": "MemRecall", "mem.forget": "MemForget",
    "jarvis.install_plugin": "Install", "jarvis.uninstall_plugin": "Uninstall",
    "plugin.log_change": "LogChange", "agent.identity": "Identity",
    "self.whoami": "Whoami", "self.capabilities": "Capabilities",
    "self.version": "Version", "self.config": "Config",
    "hass.light_on": "LightOn", "hass.light_off": "LightOff", "hass.status": "HAStatus",
}


def _display_name(name: str) -> str:
    return _KNOWN_TOOLS.get(name, name.split(".")[-1].title() or name)


def _short(value: str, limit: int = 48) -> str:
    """Truncate a rendered value so tool labels stay on one line."""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _tool_label(
    name: str,
    arguments: dict,
    max_args: int = 4,
    arg_limit: int = 48,
    max_len: int = 110,
) -> str:
    """One-line tool label: display name + first args, values truncated."""
    args = ", ".join(
        f"{k}={_short(_esc(repr(v)), arg_limit)}"
        for k, v in list(arguments.items())[:max_args]
    )
    label = f"{_display_name(name)}({args})"
    if len(label) > max_len:
        label = label[: max_len - 3] + "..."
    return label


def _esc(text: str) -> str:
    """Escape literal square brackets for Rich markup (avoid MarkupError)."""
    return text.replace("[", "\\[")


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


class _SplashScreen(Screen):
    """Startup splash: big-font JARVIS title with blue-white shimmer + tagline."""

    CSS = """
    #splash-root { align: center middle; }
    #splash-big { width: auto; }
    #splash-tag { width: auto; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="splash-root"):
            yield Static("", id="splash-big")
            yield Static(f"{_DIM}microkernel · everything is a plugin[/]", id="splash-tag")

    def on_mount(self) -> None:
        self._big_rows = render_big("JARVIS")
        self._step = 0
        self._stimer = self.set_interval(0.05, self._shimmer)
        # dismiss() returns an awaitable; wrap it so set_timer does not await it
        self.set_timer(2.8, self._dismiss_now)

    def _dismiss_now(self) -> None:
        self.dismiss()

    def _shimmer(self) -> None:
        rows = "\n".join(shimmer_line(row, self._step) for row in self._big_rows)
        self.query_one("#splash-big", Static).update(rows)
        self._step += 1


class _JarvisApp(App):
    """Textual app: output panel + input box + header/footer."""

    CSS = """
    Screen { background: $background; }
    #chat {
        height: 1fr;
        margin: 0 1;
        scrollbar-color: $primary;
    }
    .msg {
        width: 100%;
        padding: 0 1;
    }
    .user-msg {
        background: $surface;
        margin-top: 1;
    }
    .assistant-msg {
        margin-top: 1;
    }
    .thinking-msg {
        color: $text 70%;
        margin-top: 1;
    }
    .tool-msg {
        color: $text 70%;
    }
    #status {
        height: 1;
        margin: 0 2;
        content-align: left middle;
        color: $primary;
    }
    #input-row {
        dock: bottom;
        height: 3;
        margin: 0 1 1 1;
        padding: 0 2;
        background: $surface;
        border: round $primary;
    }
    #input-row:focus-within {
        border: round $accent;
        background: $panel;
    }
    #input-prompt {
        width: auto;
        content-align: center middle;
        color: $primary;
        margin-right: 1;
    }
    #in {
        border: none;
        background: transparent;
        height: 100%;
        padding: 0;
    }
    #brand {
        height: auto;
        margin: 0 1 1 1;
        content-align: center top;
    }
    #brand.hidden {
        display: none;
    }
    Header { background: $surface; color: $text; }
    Footer { background: $surface; }
    """

    BINDINGS = [
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear output"),
        ("ctrl+o", "toggle_thinking", "Toggle thinking"),
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
        # structured message list state
        self._assistant_buf: list[str] = []
        self._current_assistant = None
        self._current_thinking = None
        self._thinking = ""
        self._thinking_visible = False
        self._current_tool = None
        self._current_tool_label = ""
        self._tool_spinner_idx = 0
        self._tool_spinner_timer = None
        # the thread that owns the app: worker threads must hop over via
        # call_from_thread, direct calls (tests / sync callers) can run inline
        self._ui_thread_id = threading.get_ident()

    def _ui_call(self, fn, *args):
        """Run fn on the app thread (worker-thread-safe); when already on the
        app thread (tests / synchronous callers) run it directly."""
        if threading.get_ident() == self._ui_thread_id:
            return fn(*args)
        return self.call_from_thread(fn, *args)

    # ---- UI wiring ----
    def compose(self) -> ComposeResult:
        yield Static("", id="brand")
        yield Header(show_clock=True)
        yield VerticalScroll(id="chat")
        yield Static("", id="status")
        with Horizontal(id="input-row"):
            yield Static("❯ ", id="input-prompt")
            yield Input(id="in", placeholder="message JARVIS... (\\ continues a line, /help for commands)")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.register_theme(_THEME)
            self.theme = "jarvis-dark"
        except Exception:  # noqa: BLE001 - already registered / older textual
            pass
        self._kernel.confirm_action = self._confirm_wait
        self._brand_rows = render_big("JARVIS")
        self._brand_step = 0
        self._brand_timer = self.set_interval(0.1, self._brand_shimmer)
        self._brand_shimmer()
        state = "ON" if self._kernel.auto_approve() else "OFF"
        self._log(
            f"{_PRIMARY}JARVIS >[/] ready. Type /help for commands. "
            f"auto-approve: {_GREEN if state == 'ON' else _DIM}{state}[/]"
        )
        # replay the persisted conversation so a restart doesn't lose context
        try:
            for m in self._kernel.history("terminal"):
                self._render_history(m)
        except Exception:  # noqa: BLE001
            pass
        self._focus_input()
        self.push_screen(_SplashScreen())

    def _render_history(self, m) -> None:
        """Render one persisted history message at startup (no re-animation).

        Assistant messages go through the SAME built-in markdown renderer as
        live streaming (headings/lists/bold/code), so replayed conversations
        look identical to the live flow.
        """
        if m.role == "user":
            self._new_message(f"{_SECONDARY}you >[/] {_esc(m.content)}", "user-msg")
        elif m.role == "assistant" and m.content:
            # render historically stored text through the md pipeline
            self._assistant_buf = []
            self._assistant_prefix = False
            self._md_part = ""
            self._in_code = False
            for ln in m.content.split("\n"):
                self._assistant_buf.append(self._md_line(ln))
            self._refresh_assistant()
            # never let an unclosed code fence from history leak into live
            # streaming state
            self._in_code = False
            self._md_part = ""
        elif m.role == "tool":
            first = (m.content or "").strip().split("\n", 1)[0]
            self._new_message(f"{_DIM}  ⚙ {m.name or 'tool'}: {_short(first, 60)}[/]", "tool-msg")

    def _brand_shimmer(self) -> None:
        """Perpetual shimmer sweep on the main-view JARVIS logo (like the splash)."""
        w = self.query_one("#brand", Static)
        if "hidden" in w.classes:
            return  # narrow terminal: logo hidden, skip the sweep
        rows = "\n".join(shimmer_line(row, self._brand_step) for row in self._brand_rows)
        w.update(f"{rows}\n{_DIM}microkernel · everything is a plugin[/]")
        self._brand_step += 1

    def _log(self, text: str, classes: str = "") -> None:
        """Append a plain message row (system / tool / error lines)."""
        self._new_message(text, classes)

    def _new_message(self, markup: str, classes: str = "") -> Static:
        """Mount a message widget into the chat scroll area."""
        sv = self.query_one("#chat", VerticalScroll)
        w = Static(markup, classes=("msg " + classes).strip())
        sv.mount(w)
        sv.scroll_end(animate=False)
        return w

    def _update_message(self, widget, markup: str) -> None:
        if widget is not None:
            widget.update(markup)

    def _scroll_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

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
        self._log(f"{_ORANGE}? {_esc(prompt)} [y/N] (press y or n)[/]")
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
        self._log(f"{_DIM}-> {'yes' if ans else 'no'}[/]")

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
            self._log(f"{_DIM}queued (JARVIS busy): {_esc(text)}[/]")
            return
        self._start_chat(text)

    def on_key(self, event) -> None:
        """App-level: y/N answers a pending confirmation, regardless of focus."""
        if self._pending_confirm is not None and event.key in ("y", "Y", "n", "N", "escape"):
            self._answer_confirm(event.key.lower() in ("y",))
            self.query_one("#in", Input).value = ""
            event.stop()

    def on_resize(self) -> None:
        """Hide the brand logo on narrow terminals (dsh-TUI WHALE_MIN_COLUMNS=64)."""
        w = self.query_one("#brand", Static)
        w.set_class(self.size.width < 64, "hidden")

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
            self._log(_HELP)
        elif c in ("/exit", "/quit"):
            self.exit()
        elif c == "/clear":
            self.query_one("#chat", VerticalScroll).remove_children()
        elif c == "/autoapprove" or c.startswith("/autoapprove "):
            self._log(self._autoapprove_cmd(c))
        else:
            self._log(f"{_DIM}unknown command: {c} (try /help)[/]")

    def _autoapprove_cmd(self, cmd: str) -> str:
        """Handle /autoapprove [on|off|toggle]: live auto-approve switch.

        Toggles the kernel's auto-approve mode (bash/file/install actions no
        longer prompt y/N) and persists it to config.toml via the kernel.
        """
        parts = cmd.split()
        current = self._kernel.auto_approve()
        if len(parts) == 1:
            state = "ON" if current else "OFF"
            return (
                f"auto-approve is [bold]{state}[/] — "
                "/autoapprove on|off|toggle to change"
            )
        arg = parts[1].lower()
        if arg in ("on", "true", "yes", "1"):
            self._kernel.set_auto_approve(True)
            return "auto-approve [bold]ON[/] — assistant actions run without y/N prompts"
        if arg in ("off", "false", "no", "0"):
            self._kernel.set_auto_approve(False)
            return "auto-approve [bold]OFF[/] — confirmations restored"
        if arg == "toggle":
            self._kernel.set_auto_approve(not current)
            return f"auto-approve [bold]{'ON' if not current else 'OFF'}[/]"
        return "usage: /autoapprove [on|off|toggle]"

    # ---- chat worker ----
    def _start_chat(self, text: str) -> None:
        self._set_busy(True)
        self._md_part = ""
        self._in_code = False
        self._assistant_prefix = False
        self._turn_start = time.time()
        self._thinking = ""
        self._thinking_visible = False
        self._current_thinking = None
        self._current_assistant = None
        self._assistant_buf = []
        self._current_tool = None
        # user bubble (structured message)
        lines = text.split("\n")
        self._new_message(f"{_SECONDARY}you >[/] {_esc(lines[0])}", "user-msg")
        for extra in lines[1:]:
            self._new_message(f"  {_esc(extra)}", "user-msg")
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
                self.call_from_thread(self._log, f"{_ORANGE}[error] {_esc(str(exc))}[/]")
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
        if chunk.reasoning:
            self.call_from_thread(self._feed_thinking, chunk.reasoning)
        if chunk.text:
            # text arriving: drop the thinking/tool spinner (re-armed by _on_tool)
            self.call_from_thread(self._stop_spinner)
            self.call_from_thread(self._stream_md, chunk.text)

    def _feed_thinking(self, text: str) -> None:
        self._thinking += text
        if self._current_thinking is None:
            self._current_thinking = self._new_message("Thinking... (ctrl+o to expand)", "thinking-msg")
        self._update_thinking()

    def _update_thinking(self) -> None:
        if self._current_thinking is None:
            return
        if self._thinking_visible:
            self._update_message(self._current_thinking, f"Thinking (expanded):\n{_esc(self._thinking)}")
        else:
            self._update_message(self._current_thinking, f"Thinking... ({len(self._thinking)} ch, ctrl+o)")
        self._scroll_end()

    def action_toggle_thinking(self) -> None:
        if self._current_thinking is None:
            return
        self._thinking_visible = not self._thinking_visible
        self._update_thinking()

    # ---- streaming markdown -> rich markup ----
    def _stream_md(self, text: str) -> None:
        """Feed a streamed assistant chunk; render complete lines as md."""
        text = self._md_part + text
        lines = text.split("\n")
        self._md_part = lines.pop()
        for ln in lines:
            self._assistant_buf.append(self._md_line(ln))
        self._refresh_assistant()

    def _refresh_assistant(self) -> None:
        """Render completed lines PLUS the live in-flight line, so streamed
        text is visible the moment a chunk arrives (not only after a newline)."""
        lines = list(self._assistant_buf)
        if self._md_part:
            # pure render of the unterminated line: no fence-state transitions
            lines.append(_md_block(self._md_part, self._in_code))
        if not lines:
            return
        if not self._assistant_prefix:
            self._assistant_prefix = True
            lines[0] = f"{_PRIMARY}jarvis >[/] {lines[0]}"
        if self._current_assistant is None:
            self._current_assistant = self._new_message("", "assistant-msg")
        self._update_message(self._current_assistant, "\n".join(lines))
        self._scroll_end()

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
            self._assistant_buf.append(self._md_line(self._md_part))
            self._md_part = ""
        self._in_code = False
        self._refresh_assistant()
    def _on_tool(self, call) -> None:
        # Called from the chat worker thread: ALL UI mutation must run on the
        # app thread via call_from_thread, or textual's DOM races and tool
        # messages can silently fail to appear / glitch.
        self._ui_call(self._handle_tool_call, call)

    def _handle_tool_call(self, call) -> None:
        label = _tool_label(call.name, call.arguments or {})
        self._current_tool_label = label
        self._tool_started = time.time()
        # Seal the streaming assistant block: flush any partial line, then
        # reset so continued text opens a NEW widget BELOW this tool row.
        # Without this, all text accumulates in one top widget and the tool
        # records all stack below it (no interleaved flow).
        try:
            self._flush_md()
        except Exception:  # noqa: BLE001
            pass
        self._assistant_buf = []
        self._assistant_prefix = False
        self._current_assistant = None
        self._current_tool = self._new_message(
            f"{_SECONDARY}  {_SPINNER[0]} {label} (0.0s)[/]", "tool-msg"
        )
        self._tool_spinner_idx = 1
        if self._tool_spinner_timer is None:
            self._tool_spinner_timer = self.set_interval(0.1, self._tick_tool_spinner)
        self._start_spinner(f"working: {label}")

    def _tick_tool_spinner(self) -> None:
        if self._current_tool is not None:
            frame = _SPINNER[self._tool_spinner_idx % len(_SPINNER)]
            self._tool_spinner_idx += 1
            elapsed = time.time() - self._tool_started if self._tool_started else 0.0
            self._update_message(
                self._current_tool,
                f"{_SECONDARY}  {frame} {self._current_tool_label} ({elapsed:.1f}s)[/]",
            )

    def _on_tool_done(self, call, result: str, duration: float) -> None:
        self._ui_call(self._handle_tool_done, call, result, duration)

    def _handle_tool_done(self, call, result: str, duration: float) -> None:
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
            self._tool_spinner_timer = None
        summary = _short(_esc((result or "").strip().split("\n", 1)[0]), 60)
        denied = "not confirmed" in result or result.startswith("[error]") or "refused" in result
        mark = "✗" if denied else "✓"
        color = _DIM if denied else _GREEN
        if self._current_tool is not None:
            self._update_message(
                self._current_tool,
                f"{color}  {mark} {self._current_tool_label} -> {summary} ({duration:.1f}s)[/]",
            )
        self._current_tool = None
        # The tool result goes back to the model, which thinks again. Re-arm
        # the status spinner so multi-round turns never look stalled; the next
        # text chunk (_on_chunk) or _finish_turn stops it.
        self._start_spinner("thinking...")

    def _finish_turn(self) -> None:
        self._flush_md()
        self._stop_spinner()
        self._set_busy(False)
        elapsed = time.time() - self._turn_start if self._turn_start else 0.0
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
        self.query_one("#chat", VerticalScroll).remove_children()
        self._current_assistant = None
        self._current_thinking = None
        self._current_tool = None
        self._assistant_buf = []
        self._thinking = ""
        self._thinking_visible = False


_HELP = """
[bold cyan]Commands[/]
  /help /clear /exit
  /autoapprove [on|off|toggle]   control the auto-approve switch

[bold cyan]Input[/]
  - end a line with backslash to continue on the next line
  - up/down arrows browse history
  - typing while JARVIS is busy queues your message
  - tool confirmations are answered with y/N on the keyboard
  - ctrl+o expands/collapses the thinking block
  - ctrl+d quits, ctrl+l clears the chat
"""


class _TuiChannel:
    kind = "tui"

    def run(self, kernel) -> None:
        if not _TEXTUAL_OK:
            print("[channel-tui] textual not installed - run: uv pip install -e .[ui]")
            return
        _JarvisApp(kernel).run()

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 02:52:00 ---