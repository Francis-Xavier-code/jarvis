"""Minimal Markdown -> ANSI renderer for the terminal channel.

Zero hard dependencies: works with the Python standard library only.
If `rich` is installed, :func:`render_md` defers to it for nicer output
(tables, syntax-highlighted code); otherwise it falls back to a small
built-in ANSI formatter.

Design notes (JARVIS "everything is a plugin"): *presentation* is the
channel's job. The LLM emits Markdown (Telegram renders it natively; the
terminal cannot), so this channel translates it to something readable.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

# ANSI SGR codes we use (kept minimal + widely supported).
_BOLD = "\033[1m"
_DIM = "\033[2m"
_ITAL = "\033[3m"
_UNDER = "\033[4m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RESET = "\033[0m"

_USE_COLOR = (
    sys.stdout.isatty()
    and not os.environ.get("NO_COLOR")
    and os.environ.get("TERM", "dumb") != "dumb"
)


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"{code}{text}{_RESET}"


def _strip_inline(text: str) -> str:
    """Remove inline markdown markers, keeping the text readable."""
    text = re.sub(r"`([^`]+)`", lambda m: _c(_CYAN, m.group(1)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: _c(_BOLD, m.group(1)), text)
    text = re.sub(r"__([^_]+)__", lambda m: _c(_BOLD, m.group(1)), text)
    text = re.sub(r"\*([^*]+)\*", lambda m: _c(_ITAL, m.group(1)), text)
    text = re.sub(r"_([^_]+)_", lambda m: _c(_ITAL, m.group(1)), text)
    text = re.sub(r"~~([^~]+)~~", lambda m: _c(_DIM, m.group(1)), text)
    # links: [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def _render_block(md: str) -> str:
    """Render block-level markdown to ANSI text."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    in_code = False
    code_buf: list[str] = []
    list_depth = 0

    def flush_code() -> None:
        nonlocal code_buf, in_code
        if code_buf:
            fence = _c(_DIM, "┌─ code ─" + "─" * max(0, 20 - len("┌─ code ─")))
            out.append(fence)
            for cl in code_buf:
                out.append(_c(_CYAN, "│ " + cl))
            out.append(_c(_DIM, "└" + "─" * 24))
        code_buf = []
        in_code = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # fenced code block
        if stripped.startswith("```"):
            if in_code:
                flush_code()
            else:
                in_code = True
                code_buf = []
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            content = _strip_inline(m.group(2))
            prefix = "#" * level + " "
            out.append(_c(_BOLD + _YELLOW, prefix + content))
            i += 1
            continue

        # horizontal rule
        if re.match(r"^(\*{3,}|_{3,}|-{3,})\s*$", stripped):
            out.append(_c(_DIM, "─" * 40))
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            content = _strip_inline(stripped.lstrip("> ").strip())
            out.append(_c(_DIM, "│ " + content))
            i += 1
            continue

        # unordered list
        m = re.match(r"^(\s*)([-*+])\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            content = _strip_inline(m.group(3))
            bullet = _c(_GREEN, "•" if indent == 0 else "–")
            out.append("  " * indent + bullet + " " + content)
            i += 1
            continue

        # ordered list
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            content = _strip_inline(m.group(3))
            num = _c(_GREEN, m.group(2) + ".")
            out.append("  " * indent + num + " " + content)
            i += 1
            continue

        # blank line
        if not stripped:
            out.append("")
            i += 1
            continue

        # paragraph (may contain inline markers)
        out.append(_strip_inline(line))
        i += 1

    if in_code:
        flush_code()
    return "\n".join(out)


def render_md(md: str) -> str:
    """Render Markdown ``md`` to terminal-friendly text.

    Uses ``rich`` when available for the best result; otherwise the built-in
    ANSI renderer. Never raises on plain text.
    """
    if not md:
        return md
    if _USE_COLOR and shutil.which("rich") is not None:
        try:  # pragma: no cover - optional path
            from rich.console import Console
            from rich.markdown import Markdown

            console = Console(file=sys.stdout, soft_wrap=True)
            with console.capture() as cap:
                console.print(Markdown(md))
            return cap.get().rstrip("\n")
        except Exception:  # noqa: BLE001 - fall back gracefully
            pass
    return _render_block(md)
