# JARVIS Plugin Specification (v1.0 — frozen)

This is the contract between **plugin authors** and the **JARVIS microkernel**.
Follow it and any git repo becomes a usable JARVIS plugin the moment it is
cloned — no kernel changes, no special registration. The kernel discovers a
plugin by scanning `plugins/<dir>/plugin.toml`; everything else is derived.

> **v1.0 is FROZEN.** All previously open decisions are now settled (see §8).
> Future changes are versioned (v1.1, v2.0, ...). Items marked **[GAP]** are
> declared-but-not-implemented and will be closed in a later version.

---

## 1. Directory layout

A plugin is a directory under `plugins/`:

```
plugins/<dir>/
├── plugin.toml      # REQUIRED — the manifest
├── plugin.py        # REQUIRED — the entrypoint (name from manifest `entry`)
├── README.md        # REQUIRED — plugin's own docs (see §7.1)
└── <other files>   # any supporting code
```

- `<dir>` is the **clone/disk name** (from the git URL or the `name` override).
  It may differ from the manifest `name`; the kernel keys the plugin by its
  manifest `name` after load.
- Cloned plugins get a `.jarvis-cloned` marker and are gitignored (they are
  pulled at runtime, never committed as source).

---

## 2. Manifest — `plugin.toml`

TOML with exactly one `[plugin]` table:

| field        | type     | required | default     | meaning |
|--------------|----------|----------|-------------|---------|
| `name`       | string   | yes      | —           | canonical plugin id; must be unique across loaded plugins |
| `kind`       | string   | yes      | —           | one of `provider` \| `memory` \| `channel` \| `config` \| `tool` |
| `version`    | string   | no       | `"0.0.0"`   | semver-ish, informational |
| `entry`      | string   | no       | `"plugin.py"` | entrypoint filename inside the dir |
| `hot_reload` | bool     | no       | `true`      | if false, the kernel never auto-reloads it on file change |
| `dependencies` | list   | no       | `[]`        | **[GAP]** declared but NOT auto-installed (see §6) |
| `provides`   | table    | no       | `{}`        | informational: lists tool/service names this plugin exposes |

Example:

```toml
[plugin]
name = "jarvis-homeassistant"
kind = "tool"
version = "0.1.0"
entry = "plugin.py"
hot_reload = true

[provides]
tools = ["hass.light_on", "hass.light_off", "hass.status"]
```

Invalid manifests are skipped (recorded in `manager._load_errors`, surfaced by
`jarvis bootstrap`).

---

## 3. Entrypoint — `plugin.py`

Must define:

```python
from jarvis.types import KernelApi

def setup(kernel: KernelApi) -> None:
    # register tools and/or services here
    ...

def teardown(kernel: KernelApi) -> None:
    # optional; called before a hot-reload or uninstall
    ...
```

### 3.1 Registering tools

```python
@kernel.tool("hass.light_on", "Turn on a light", {"entity_id": {"type": "string"}})
def light_on(entity_id: str) -> str:
    return f"turned on {entity_id}"
```

- The tool `name` is **namespaced by convention**: prefix with the plugin name
  (`hass.*`, `demo.*`) to avoid collisions. The kernel does not enforce this,
  but collisions overwrite.
- The decorated function receives **already-parsed keyword arguments** from the
  LLM's tool_call and must return a **`str`** (the kernel `str()`s the result).
  **v1.0 rule: tool return type is `str`-only.** Structured (dict/JSON) returns
  are deferred to a later version.
- Parameter schema is **loose** for v1.0: a JSON-schema-ish dict, passed through
  to the LLM as-is. Strict validation is a later addition.

### 3.2 Registering services (by `kind`)

```python
class _EchoProvider:
    kind = "provider"
    def chat(self, req): ...

kernel.service("provider", _EchoProvider())
```

Only one service per `kind` is active (last registered wins). `kind` must match
the manifest `kind` for the plugin to be meaningful:

| kind       | expected service interface |
|------------|----------------------------|
| `provider` | `.chat(req) -> iterable[ChatChunk]` (see §5) |
| `memory`   | `.load(session) -> list[ChatMessage]`, `.append(session, msg)` |
| `channel`  | `.run(kernel)` (blocking REPL/loop) |
| `config`   | `.snapshot() -> dict`, `.get(key, default)` |
| `tool`     | no service required (just registers tools) |

### 3.3 Reading config

```python
cfg = kernel.config          # ConfigApi
token = cfg.get("ha_token", "")
cfg.watch("ha_token", lambda k, v: ...)   # optional change hook
```

Config is owned by the `config` plugin (`config-core`); other plugins read it
through this API. **v1.0 rule: config is free-form** — `get`/`watch` with no
enforced schema. Validation, if desired, is the config plugin's own concern.

---

## 4. Lifecycle & hot-reload

1. **Load**: kernel imports `entry`, calls `setup(KernelApi)`. Tools/services
   registered against the kernel's global tables.
2. **Hot-reload**: the `PluginManager` watches each plugin dir for
   mtime/content change. On change it calls `teardown` (if present), unregisters
   that plugin's tools/services, re-imports, and calls `setup` again —
   **without restarting the process**.
3. **In-flight safety**: each conversation turn takes a *snapshot* of the tool
   table, so a reload mid-turn only affects the next turn, never a running one.
4. **Uninstall**: `teardown` → unregister → drop from registry.

> **[GAP]** the watcher is currently invoked manually
> (`kernel.run_hot_reload_check()`). A background thread / file-watch should
> drive it automatically (planned).

---

## 5. Provider protocol (for `kind = provider`)

A provider plugin's `.chat(req)` is a **sync generator** yielding `ChatChunk`s:

```python
from jarvis.types import ChatChunk, ChatRequest, ToolCall

def chat(self, req: ChatRequest):
    yield ChatChunk(text="thinking...")
    yield ChatChunk(tool_call=ToolCall(name="hass.status", arguments={"entity_id": "x"}))
```

- `ChatRequest` carries `messages`, `tools` (the snapshot), `model`.
- A chunk may carry `text` and/or `tool_call`. The kernel collects text, and any
  `tool_call` is routed to the registered tool, result fed back, repeated until
  a turn yields no tool calls (max 4 rounds).
- **v1.0 rule: provider `chat` is synchronous.** `async def chat` is deferred to
  a later version (planned alongside the first real HTTP/LLM provider). The agent
  loop is sync for v1.0.

---

## 6. Dependencies

`dependencies` in `plugin.toml` is **declared but not acted upon** by v1.0 — the
kernel does **not** `pip install` anything. Two safe patterns for v1.0:

- Use only the **core dependencies** (click, pydantic, tomllib).
- **Soft-import** extras and degrade gracefully, e.g. the HA example does
  `try: import requests except ImportError: requests = None` and reports a clear
  "missing dependency" message when the tool is called.

> **v1.0 rule: NO auto-install of plugin dependencies.** This is a deliberate
> security + YAGNI stance (avoids supply-chain/network risk on clone). A plugin
> that needs an extra package must document it and rely on soft-import + a clear
> runtime message. Auto-install may be reconsidered in a later version behind an
> explicit opt-in flag.

---

## 7. Authoring checklist

To make a repo cloneable as a JARVIS plugin:

- [ ] root has `plugin.toml` with valid `[plugin]` (`name`, `kind`)
- [ ] `entry` file defines `setup(kernel)` (and optionally `teardown`)
- [ ] tools registered with unique, namespaced names
- [ ] any extra imports are soft-imported (since deps aren't auto-installed)
- [ ] config read via `kernel.config`, not hardcoded secrets in source
- [ ] tool functions return `str`
- [ ] **`README.md` present** describing what the plugin is, what it exposes, and
      how to configure/use it (see §7.1)

That's the whole contract. **Pull it in with `jarvis install <url>` or list it
in `plugin-sources.toml` for `jarvis bootstrap`.**

### 7.1 Plugin README (required)

Every plugin ships its **own** `README.md` so users know what it does without
reading source. It must cover, at minimum:

- **What it is** — one-paragraph purpose.
- **kind + provided surface** — the `kind`, and every tool/service it registers,
  with signatures and a one-line description. Tool signatures should stay in sync
  with the actual `@kernel.tool(...)` calls in `plugin.py`.
- **Configuration** — which config keys (or env vars) it reads, with examples.
- **Dependencies** — any soft-imported packages the user may need to install.
- **Install** — how to pull it (`jarvis install <url>` or `plugin-sources.toml`).
- **Security notes** — especially for plugins that execute code, hit the network,
  or clone other repos.

The 6 bundled plugins (`config-core`, `provider-echo`, `memory-jsonl`,
`channel-terminal`, `jarvis-install`, `jarvis-homeassistant`) each include a
`README.md` that follows this template.

---

## 8. v1.0 frozen decisions

| Topic | v1.0 rule |
|-------|-----------|
| Tool return type | `str`-only (kernel `str()`s the result) |
| Provider `chat` | synchronous generator (`sync` for v1.0) |
| Plugin dependencies | **no auto-install**; soft-import + graceful message |
| Config | free-form `get`/`watch`, no enforced schema |

Everything else in this document describes the kernel's enforced behaviour as of
v1.0. Future changes ship as new spec versions (v1.1, v2.0, ...) and are
backward-compatible unless a breaking change is explicitly called out.

