"""jarvis-homeassistant: an EXAMPLE plugin proving "pull a repo -> use it".

This is the template for the Home Assistant integration you described. It is a
normal JARVIS plugin that, once cloned into plugins/, exposes hass.* tools. It
talks to a Home Assistant instance over its REST API (long-lived token auth).

NOTE: this plugin does NOT clone the official HA repo — it follows the JARVIS
plugin convention and calls HA's HTTP API internally. That is the whole point
of the puller: any repo with a plugin.toml becomes usable, regardless of what
it does inside.

Config (via config-core plugin.toml or env):
  ha_base_url  e.g. http://homeassistant.local:8123
  ha_token     long-lived access token
"""
from __future__ import annotations

import os

try:
    import requests  # soft dependency: only needed when a hass tool is actually called
except ImportError:  # pragma: no cover
    requests = None

from jarvis.types import ConfigApi, KernelApi


def _cfg(kernel: KernelApi) -> dict:
    cfg: ConfigApi = kernel.config
    return {
        "base": cfg.get("ha_base_url", os.environ.get("HA_BASE_URL", "")),
        "token": cfg.get("ha_token", os.environ.get("HA_TOKEN", "")),
    }


def _call(path: str, method: str = "get", json: dict | None = None) -> str:
    if requests is None:
        return "[hass] missing dependency: pip install requests"
    base = os.environ.get("_HA_BASE", "")
    token = os.environ.get("_HA_TOKEN", "")
    if not base:
        return "[hass] not configured (set ha_base_url/ha_token)"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.request(method, f"{base}/api/{path}", headers=headers, json=json, timeout=10)
    return f"{r.status_code}: {r.text[:200]}"


def setup(kernel: KernelApi) -> None:
    @kernel.tool("hass.light_on", "Turn on a light entity", {"entity_id": {"type": "string"}})
    def light_on(entity_id: str) -> str:
        return _call(f"services/light/turn_on", "post", {"entity_id": entity_id})

    @kernel.tool("hass.light_off", "Turn off a light entity", {"entity_id": {"type": "string"}})
    def light_off(entity_id: str) -> str:
        return _call(f"services/light/turn_off", "post", {"entity_id": entity_id})

    @kernel.tool("hass.status", "Get the state of an entity", {"entity_id": {"type": "string"}})
    def status(entity_id: str) -> str:
        return _call(f"states/{entity_id}")


def teardown(kernel: KernelApi) -> None:
    pass
