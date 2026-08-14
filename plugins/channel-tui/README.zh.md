# channel-tui

A full-screen **TUI** channel built on **textual** — output and input live in
separate panels, so typing while JARVIS streams never interleaves with the
reply (no more "printf mess").

- **kind**: `channel` (kind `tui`)
- **run**: `jarvis tui`

## Features

* streamed assistant text in a scrollable output panel
* tool calls and completions shown inline (⚙ / ✓ / ✗ + duration)
* confirmation prompts answered inline in the input row (y/N on keyboard - no popup over the output)
* single-line input with up/down history and `\` continuation
* busy state in the header; input typed while busy is queued
* ctrl+d quit, ctrl+l clear output, `/help` `/clear` `/exit`

## Install

```bash
uv pip install -e ".[ui]"   # installs textual
uv run jarvis bootstrap
uv run jarvis tui
```

The plugin is soft-imported: without textual it loads but `jarvis tui` shows
an install hint. The streaming REPL (`jarvis chat`) remains available.
