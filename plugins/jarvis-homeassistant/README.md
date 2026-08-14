# jarvis-homeassistant  (EXAMPLE / TEMPLATE)

Proof of the core claim: **pull a repo → it becomes a usable JARVIS plugin**.
This plugin talks to a Home Assistant instance over its REST API.

- **kind**: `tool`
- **provides** three tools:

```
hass.light_on(entity_id: str) -> str
    Turn on a light entity, e.g. "light.living_room".

hass.light_off(entity_id: str) -> str
    Turn off a light entity.

hass.status(entity_id: str) -> str
    Get the current state of an entity.
```

## Configuration

Set via the `config-core` plugin's `config.toml`, or environment variables:

| Key (config.toml) | Env var     | Example |
|-------------------|-------------|---------|
| `ha_base_url`     | `_HA_BASE`  | `http://homeassistant.local:8123` |
| `ha_token`       | `_HA_TOKEN` | long-lived access token |

If unset, tools return `[hass] not configured (set ha_base_url/ha_token)`.

## Dependency

Uses `requests` (soft-imported). Install it once in the JARVIS venv if you
actually call a `hass.*` tool:

```
uv pip install requests
```

## Important

This is a **template**, not the official Home Assistant repo. The official HA
repo does not follow the JARVIS `plugin.toml` convention, so it cannot be cloned
directly — this wrapper adapts HA's REST API into JARVIS tools. Clone it, set
your config, and the `hass.*` tools become available immediately.
