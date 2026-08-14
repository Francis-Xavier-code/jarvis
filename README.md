# JARVIS

> A microkernel AI assistant where **everything is a plugin**.

> 中文文档: [README.zh.md](README.zh.md)

JARVIS is built on one rule: the kernel does almost nothing. LLM providers,
memory backends, conversation channels (terminal / telegram / web), **and even
configuration** are all *plugins*. Each plugin is a plain directory under
`plugins/` containing a `plugin.toml` manifest and a `plugin.py` entrypoint.

A plugin registers tools and services against the kernel. The kernel aggregates
them into a single tool table and runs the agent loop. Plugins support
**hot-reload**: change a plugin's files (or its config) and the kernel tears it
down and reloads it — no process restart, and in-flight conversations are safe
because each turn uses a snapshot of the tool table.

## Layout

```
jarvis/            # the microkernel (types, plugin manager, kernel, cli)
plugins/           # every capability lives here as a plain subdirectory
  config-core/     # config is a plugin (holds config.toml, exposes get/watch)
  provider-openai/ # real LLM brain (OpenAI-compatible; default = opencodego)
  memory-jsonl/    # per-session conversation history (JSONL)
  channel-terminal/# terminal REPL channel
  jarvis-install/  # the pull capability, exposed as a plugin
  jarvis-homeassistant/ # EXAMPLE: HA wrapper proving "clone -> usable plugin"
  plugin-self/     # self-awareness (whoami / capabilities / version)
```

## Run

```bash
uv venv && uv pip install -e .
uv run jarvis chat        # terminal REPL
uv run jarvis bootstrap   # list loaded plugins + any load errors
```

## Write a plugin

Create `plugins/my-thing/plugin.toml`:

```toml
[plugin]
name = "my-thing"
kind = "tool"            # provider | memory | channel | config | tool
version = "0.1.0"
entry = "plugin.py"
hot_reload = true
```

And `plugins/my-thing/plugin.py`:

```python
from jarvis.types import KernelApi

def setup(kernel: KernelApi) -> None:
    @kernel.tool("my_thing.greet", "Greet someone", {"name": {"type": "string"}})
    def greet(name: str = "world") -> str:
        return f"hello, {name}"
```

Drop the folder in `plugins/` and it is loaded on next start (or hot-reloaded
the moment you edit it). No kernel changes required.

## Roadmap (post-mechanism)

- Real `provider-*` plugins (OpenAI-compatible endpoints)
- `channel-telegram` (long-poll bot) and `channel-web`
- `tool-homeassistant` demo plugin
- Optional: promote selected plugins to independent git repos with auto-pull
