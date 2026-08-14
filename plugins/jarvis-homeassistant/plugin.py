"""jarvis-homeassistant: lights control — LOCAL-first, zero external services.

Dual-mode light control:
  * local mode (default, no config): light state lives in <data_dir>/lights.json.
    Pure plugin, no Home Assistant, no HTTP, no Docker — fully self-contained.
  * home-assistant mode: when [homeassistant] ha_base_url + ha_token are
    configured, tools talk to a real Home Assistant over its REST API
    (long-lived token auth) and the local store is ignored.

Same hass.* tool names in both modes, so wiring a real HA later is a config
change only.

Config (via config-core plugin.toml or env):
  homeassistant.ha_base_url  e.g. http://homeassistant.local:8123
  homeassistant.ha_token     long-lived access token
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    import requests  # soft dependency: only needed in home-assistant mode
except ImportError:  # pragma: no cover
    requests = None

from jarvis.types import ConfigApi, KernelApi

_DEFAULT_LIGHTS = {
    "light.living_room": {"state": "off", "friendly_name": "客厅灯"},
    "light.bedroom": {"state": "off", "friendly_name": "卧室灯"},
    "light.desk": {"state": "on", "friendly_name": "书桌灯"},
}


def _cfg(kernel: KernelApi) -> dict:
    cfg: ConfigApi = kernel.config
    return {
        "base": cfg.get("homeassistant.ha_base_url") or os.environ.get("HA_BASE_URL", ""),
        "token": cfg.get("homeassistant.ha_token") or os.environ.get("HA_TOKEN", ""),
    }


# ---- local store (pure-plugin mode) ----
def _store(kernel: KernelApi) -> Path:
    return Path(kernel.data_dir) / "lights.json"


def _load(kernel: KernelApi) -> dict:
    p = _store(kernel)
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved:
                return saved
        except Exception:  # noqa: BLE001
            pass
    return dict(_DEFAULT_LIGHTS)


def _save(kernel: KernelApi, data: dict) -> None:
    try:
        _store(kernel).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _local_set(kernel: KernelApi, entity_id: str, state: str) -> str:
    data = _load(kernel)
    if entity_id not in data:
        known = ", ".join(sorted(data))
        return f"[lights] unknown entity {entity_id} (known: {known})"
    data[entity_id]["state"] = state
    _save(kernel, data)
    return f"[lights] {entity_id} -> {state} ({time.strftime('%H:%M:%S')})"


def _local_status(kernel: KernelApi, entity_id: str) -> str:
    data = _load(kernel)
    ent = data.get(entity_id)
    if ent is None:
        known = ", ".join(sorted(data))
        return f"[lights] unknown entity {entity_id} (known: {known})"
    name = ent.get("friendly_name", entity_id)
    return f"{name} ({entity_id}): {ent.get('state', 'unknown')}"


# ---- home-assistant mode (REST) ----
def _ha_call(base: str, token: str, path: str, method: str = "get", json_body: dict | None = None) -> str:
    if requests is None:
        return "[hass] missing dependency: pip install requests"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        r = requests.request(method, f"{base}/api/{path}", headers=headers, json=json_body, timeout=10)
        return f"{r.status_code}: {r.text[:200]}"
    except Exception as exc:  # noqa: BLE001
        return f"[hass] request failed: {exc}"


def setup(kernel: KernelApi) -> None:
    # Tools re-read config on every call, so a config hot-reload (or the
    # local -> home-assistant switch) takes effect without restarting.

    @kernel.tool("hass.light_on", "Turn on a light entity", {"entity_id": {"type": "string"}})
    def light_on(entity_id: str) -> str:
        c = _cfg(kernel)
        if c["base"]:
            return _ha_call(c["base"], c["token"], "services/light/turn_on", "post", {"entity_id": entity_id})
        return _local_set(kernel, entity_id, "on")

    @kernel.tool("hass.light_off", "Turn off a light entity", {"entity_id": {"type": "string"}})
    def light_off(entity_id: str) -> str:
        c = _cfg(kernel)
        if c["base"]:
            return _ha_call(c["base"], c["token"], "services/light/turn_off", "post", {"entity_id": entity_id})
        return _local_set(kernel, entity_id, "off")

    @kernel.tool("hass.status", "Get the state of an entity", {"entity_id": {"type": "string"}})
    def status(entity_id: str) -> str:
        c = _cfg(kernel)
        if c["base"]:
            return _ha_call(c["base"], c["token"], f"states/{entity_id}")
        return _local_status(kernel, entity_id)


def teardown(kernel: KernelApi) -> None:
    pass

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 05:25:23 ---
