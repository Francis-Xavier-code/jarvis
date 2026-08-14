"""mdcat-render: markdown -> beautiful ANSI terminal output via the mdcat CLI.

Wraps the `mdcat` binary ("fancy cat for markdown", Rust - CommonMark with
bat syntax highlighting, themes, mermaid, math, GFM alerts...). Two surfaces:

1. Tools (kind="tool"):
     md.render(text, theme?, ansi?)       - render markdown TEXT
     md.render_file(path, theme?, ansi?)  - render a markdown FILE
   ANSI escapes are stripped by default so the output is safe to embed in any
   channel (TUI / LLM context); pass ansi=true for a raw terminal render.

2. Service (kind="render"):
     kernel.service("render", svc) - channel-terminal's buffered mode
   (JARVIS_NO_STREAM=1) renders replies through svc.render(text) when the
   service is present, replacing the built-in plain renderer.

Soft dependency per PLUGIN_SPEC §6: no auto-install. The mdcat binary must be
on PATH (`brew install mdcat` / `cargo install mdcat`); without it the
tools return a clear message and the render service falls back to plain text.
Config (config-core [mdcat] section): theme = "catppuccin-mocha" etc.
"""
from __future__ import annotations

import re
import shutil
import subprocess

from jarvis.types import KernelApi

MAX_OUTPUT = 200_000  # cap on rendered output (chars)
TIMEOUT = 30  # seconds for one mdcat invocation

# CSI sequences (colors/styles) and OSC sequences (links etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*?(\x07|\x1b\\)")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _binary() -> "str | None":
    return shutil.which("mdcat")


def _not_installed() -> str:
    return "[mdcat] binary not found - install it with: brew install mdcat  (or: cargo install mdcat)"


def _run_mdcat(args: list[str], data: "bytes | None") -> str:
    """Run mdcat with optional stdin data; returns output (or an error text)."""
    binary = _binary()
    if binary is None:
        return _not_installed()
    try:
        result = subprocess.run(
            [binary, *args],
            input=data,
            capture_output=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "[mdcat] timed out after {}s".format(TIMEOUT)
    except OSError as exc:
        return "[mdcat] failed to run: {}".format(exc)
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace")[:300]
        return "[mdcat] exit {}: {}".format(result.returncode, err)
    out = result.stdout.decode("utf-8", errors="replace")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n... (truncated)"
    return out


def _theme_args(kernel: KernelApi) -> list[str]:
    theme = str(kernel.config.get("mdcat.theme", "") or "").strip()
    return ["--theme", theme] if theme else []


def _theme_arg(theme: str) -> list[str]:
    theme = (theme or "").strip()
    return ["--theme", theme] if theme else []


class _RenderService:
    kind = "render"

    def __init__(self, kernel: KernelApi) -> None:
        self._kernel = kernel

    def render(self, text: str) -> str:
        """Render markdown text (ANSI kept - the caller's stdout is a tty).
        Falls back to the plain text when mdcat is not installed."""
        if _binary() is None or not text:
            return text
        return _run_mdcat([*_theme_args(self._kernel), "-"], text.encode("utf-8"))


def setup(kernel: KernelApi) -> None:
    kernel.service("render", _RenderService(kernel))

    @kernel.tool(
        "md.render",
        "Render markdown text as formatted terminal output (syntax highlighting, tables, themes) via the mdcat CLI",
        {"text": {"type": "string"}, "theme": {"type": "string"}, "ansi": {"type": "boolean"}},
    )
    def md_render(text: str, theme: str = "", ansi: bool = False) -> str:
        if _binary() is None:
            return _not_installed()
        if not text.strip():
            return "[mdcat] empty input"
        out = _run_mdcat([*_theme_arg(theme), "-"], text.encode("utf-8"))
        return out if ansi else _strip_ansi(out)

    @kernel.tool(
        "md.render_file",
        "Render a markdown file as formatted terminal output via the mdcat CLI",
        {"path": {"type": "string"}, "theme": {"type": "string"}, "ansi": {"type": "boolean"}},
    )
    def md_render_file(path: str, theme: str = "", ansi: bool = False) -> str:
        if _binary() is None:
            return _not_installed()
        if not path.strip():
            return "[mdcat] empty path"
        out = _run_mdcat([*_theme_arg(theme), path], None)
        return out if ansi else _strip_ansi(out)


def teardown(kernel: KernelApi) -> None:
    pass

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 03:33:28 ---
