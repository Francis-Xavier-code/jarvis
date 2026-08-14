"""config-core: the 'config is a plugin' proof.

Holds ``config.toml`` next to the kernel root and exposes it via the kernel's
ConfigApi (get/watch). Editing config.toml changes its mtime -> PluginManager
hot-reloads this plugin -> watchers fire. This is how 'config is a plugin'
satisfies the same hot-reload contract as every other capability.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from jarvis.types import KernelApi

CONFIG_PATH = Path(os.environ.get("JARVIS_CONFIG", "")) or (
    Path(__file__).resolve().parents[2] / "config.toml"
)


def setup(kernel: KernelApi) -> None:
    data = _read()
    kernel._kernel.set_config(data)  # type: ignore[attr-defined]
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


class _ConfigService:
    kind = "config"

    def __init__(self, data: dict) -> None:
        self._data = data

    def snapshot(self) -> dict:
        return self._data

    def get(self, key: str, default=None):
        return self._data.get(key, default)
