# mdcat-render

Render markdown as beautiful terminal output through the [mdcat](https://github.com/sharkdp/mdcat)
CLI — CommonMark with **bat syntax highlighting**, **colour themes**, tables,
mermaid diagrams, math and GFM alerts. JARVIS's own renderer is a plain ANSI
converter; mdcat is a full Rust renderer.

## What it is

A `kind="tool"` plugin with two surfaces:

1. **Tools** the assistant can call on demand:
   - `md.render(text, theme?, ansi?)` — render markdown **text**
   - `md.render_file(path, theme?, ansi?)` — render a markdown **file**
   ANSI escapes are stripped by default (safe inside the TUI / LLM context);
   pass `ansi=true` for a raw terminal render.
2. **A `render` service** — `channel-terminal`'s buffered mode
   (`JARVIS_NO_STREAM=1`) renders replies through `svc.render(text)` when
   this plugin is loaded, replacing the built-in plain renderer.

## Configuration

Via config-core (`config.toml`):

```toml
[mdcat]
theme = "catppuccin-mocha"   # optional: any mdcat/bat theme name
```

A per-call `theme` argument overrides the configured one.

## Dependencies

**mdcat binary required** (soft dependency — never auto-installed):

```bash
brew install mdcat          # macOS
cargo install mdcat         # or from source (Rust)
```

Without the binary the tools return a clear install hint and the `render`
service falls back to plain text, so nothing breaks.

## Install

```bash
jarvis install https://github.com/<you>/mdcat-render.git
# or: drop this folder into plugins/ and run jarvis bootstrap
```

## Security notes

- Renders arbitrary file paths (`md.render_file`) — read-only, no writes.
- mdcat output is capped (200 KB) and subprocesses run with a 30 s timeout.
- Rendering never executes the markdown's content (mdcat is a renderer, not a
  converter-to-executable).

<!-- --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 03:33:28 --- -->
