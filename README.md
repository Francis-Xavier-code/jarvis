<div align="center">

<img src="assess/jarvis-logo.png" alt="JARVIS logo" width="420">

**A microkernel AI assistant where *everything* is a plugin.**

`jarvis` · Python ≥ 3.11 · hot-reload · self-modifying

[中文文档](README.zh.md) &nbsp;·&nbsp; [Docs](docs/) &nbsp;·&nbsp; [Changelog](CHANGELOG.md)

</div>

---

> **One rule: the kernel does almost nothing.**
> LLM providers, memory backends, conversation channels, **even configuration** — all plugins.

JARVIS is built on that single rule. Each plugin is a plain directory under
`plugins/` with a `plugin.toml` manifest and a `plugin.py` entrypoint. Plugins
register **tools** and **services** against the kernel, which aggregates them
into one tool table and runs the agent loop.

## ✨ Features

- 🧩 **Everything is a plugin** — providers, memory, channels, config, tools
- 🔥 **Hot-reload** — edit a plugin (or its config) and it reloads live; in-flight turns are safe via tool-table snapshots
- 🧠 **Cross-session memory** — `mem.store` / `mem.recall` facts that survive restarts
- 🖥️ **Two channels** — a readline REPL (`jarvis chat`) and a full-screen TUI (`jarvis tui`)
- 📝 **Markdown-rendering TUI** — bold / lists / code blocks / links, plus an animated JARVIS splash
- 🪄 **Self-modifying** — JARVIS can edit its own plugin files, hot-load new ones, and rewire itself next turn
- 🌐 **Web tools** — search & fetch built in
- 🏠 **Home Assistant** — light control demo plugin (`clone → usable plugin` in one step)

## 🧬 Architecture

```
                  ┌──────────────────────────────────────────┐
                  │              JARVIS kernel               │
                  │  tool table · agent loop · plugin mgr    │
                  │  confirm gate · turn snapshots           │
                  └───▲───────────▲───────────▲───────────▲──┘
                      │ register  │ chat()    │ reload    │ get/watch
        ┌─────────────┴──┐   ┌────┴──────┐   ┌┴──────────┐ ┌┴─────────┐
        │  tool plugins  │   │ providers │   │ channels  │ │  config  │
        │ fs·web·hass·…  │   │  openai   │   │ terminal  │ │  core    │
        └────────────────┘   └───────────┘   │ tui       │ └──────────┘
                                             └───────────┘
```

## 📦 Layout

```
jarvis/             # the microkernel (types · plugin manager · kernel · CLI)
plugins/            # every capability lives here as a plain subdirectory
config.toml         # configuration (itself a plugin's data)
assess/             # design assets (logo · banners)
tests/              # pytest suite
# runtime data lives OUTSIDE the repo: ~/Library/Application Support/jarvis/
#   memory/memory.db — sessions + facts in one SQLite DB (memory-sql plugin)
```

## 🚀 Quickstart

```bash
uv venv && uv pip install -e ".[ui]"   # [ui] pulls textual for the TUI
uv run jarvis tui                      # full-screen TUI
uv run jarvis chat                     # terminal REPL
uv run jarvis bootstrap                # list loaded plugins + load errors
uv run jarvis doctor                   # environment checks
uv run jarvis install <git-url>        # pull a plugin repo, hot-load it
uv run jarvis check                    # one-command regression gate (compile+tests+doctor)
uv run jarvis snapshot "msg"           # git checkpoint; --undo reverts it
```

> **Fixing JARVIS?** See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — the
> golden loop is `jarvis check` → fix → `jarvis check` → `jarvis snapshot`.

## 🔌 Write a plugin

`plugins/my-thing/plugin.toml`:

```toml
[plugin]
name = "my-thing"
kind = "tool"            # provider | memory | channel | config | tool
version = "0.1.0"
entry = "plugin.py"
hot_reload = true
```

`plugins/my-thing/plugin.py`:

```python
from jarvis.types import KernelApi

def setup(kernel: KernelApi) -> None:
    @kernel.tool("my_thing.greet", "Greet someone", {"name": {"type": "string"}})
    def greet(name: str = "world") -> str:
        return f"hello, {name}"
```

Drop the folder in `plugins/` — it loads on next start, or hot-reloads the
moment you edit it. **No kernel changes required.**

## 🗂️ Plugin inventory

| plugin | kind | what it does |
|---|---|---|
| `provider-openai` | provider | the LLM brain (OpenAI-compatible, streaming SSE + tool calls) |
| `memory-jsonl` | memory | session history + cross-session facts (JSONL) |
| `memory-sql` | memory | same interface on SQLite (`memory/memory.db`, WAL, auto-migrates legacy JSONL) |
| `config-core` | config | configuration as a plugin (`get`/`watch`, hot-reload on mtime) |
| `channel-terminal` | channel | readline REPL with paste detection & multi-line input |
| `channel-tui` | channel | full-screen textual TUI: md rendering, confirm modals, tool feedback, animated splash |
| `web-tools` | tool | web search + fetch |
| `agent-tools` | tool | agent identity + file / shell tools |
| `cache-core` | tool | response caching |
| `log-stats` | tool | usage & log statistics |
| `mdcat-render` | tool | markdown → ANSI rendering via the mdcat CLI (`md.render` / `md.render_file`, `render` service for the terminal channel) |
| `personality` | tool | personality layer |
| `plugin-self` | tool | self-awareness (`whoami` / `capabilities` / `version` / `config`) |
| `jarvis-install` | tool | pull plugins from git repos at runtime |
| `jarvis-homeassistant` | tool | Home Assistant lights (demo: clone → usable plugin) |

## 🤖 "Is this repo your body?"

**Basically, yes.** The kernel is the skeleton, `plugins/` are the organs,
`config.toml` is the settings — and since the memory-sql switch, **one SQLite
database (`memory/memory.db`) is the memory center**: sessions and facts live
there, with legacy JSONL auto-migrated on first startup. A running process is
JARVIS *awake*; this repo is JARVIS *itself* — versioned in git like a genome,
and editable while running.

## 🗺️ Roadmap

- `channel-telegram` / `channel-web` — remote channels
- `/model` switching & `/resume` sessions in the TUI
- Diff views for file edits
- Promote selected plugins to independent repos with auto-pull

<!-- --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 03:33:28 --- -->
