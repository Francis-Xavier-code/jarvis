# config-core

The "config is a plugin" proof. Holds `config.toml` and exposes it to every
other plugin through the kernel's `ConfigApi` (`kernel.config.get` / `.watch`).

- **kind**: `config`
- **provides**: a config *service* (not tools)
  - `get(key, default=None)` — read a config value
  - `watch(key, cb)` — subscribe to changes on `key`
  - `snapshot()` — return the whole config dict

## Configuration

Reads `config.toml` from the project root (or the path in `JARVIS_CONFIG`).
Any key/value is allowed (free-form — see PLUGIN_SPEC §3.3 / §8). Example:

```toml
model = "gpt-4o-mini"
ha_base_url = "http://homeassistant.local:8123"
ha_token = "eyJ...long-lived-token"
```

## Why it is a plugin

Editing `config.toml` changes its mtime → the kernel hot-reloads this plugin
(teardown + reload) → watchers fire. So **configuration obeys the exact same
hot-reload contract as every other capability** — configuration is just another
plugin.

## Install

This is a core plugin shipped in `plugins/config-core/`. To pull it separately:

```
jarvis install <your-fork-url>/jarvis-config-core
```
