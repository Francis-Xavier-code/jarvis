"""config-core: the 'config is a plugin' proof.

Holds ``config.toml`` next to the kernel root and exposes it via the kernel's
ConfigApi (get/watch). Editing config.toml changes its mtime -> PluginManager
hot-reloads this plugin -> watchers fire. This is how 'config is a plugin'
satisfies the same hot-reload contract as every other capability.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from jarvis.types import KernelApi

_env_cfg = os.environ.get("JARVIS_CONFIG")
CONFIG_PATH = Path(_env_cfg) if _env_cfg else (
    Path(__file__).resolve().parents[2] / "config.toml"
)


def setup(kernel: KernelApi) -> None:
    data = _read()
    kernel.set_config(data)
    kernel.service("config", _ConfigService(data))


def teardown(kernel: KernelApi) -> None:
    pass


def _read() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _toml_value(value) -> str:
    """Serialize a single value as a TOML scalar."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return '"' + str(value) + '"'


def _write_key(path: Path, key: str, value) -> None:
    """Persist one top-level key into the TOML file, preserving comments.

    Replaces an existing ``key = ...`` line in place; otherwise inserts the
    key before the first ``[section]`` header (so it stays top-level). Missing
    file -> created with just that key.
    """
    line = f"{key} = {_toml_value(value)}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(line + "\n", encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    pat = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE)
    if pat.search(text):
        text = pat.sub(line, text)
    else:
        m = re.search(r"^\[", text, re.MULTILINE)
        if m:
            text = text[: m.start()] + line + "\n" + text[m.start():]
        else:
            text = text.rstrip() + "\n" + line + "\n"
    path.write_text(text, encoding="utf-8")


class _ConfigService:
    kind = "config"

    def __init__(self, data: dict) -> None:
        self._data = data

    def snapshot(self) -> dict:
        return self._data

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        """Update one key in memory and persist it to config.toml."""
        self._data[key] = value
        _write_key(CONFIG_PATH, key, value)

# touched
