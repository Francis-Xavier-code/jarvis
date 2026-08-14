"""PluginManager: discover, load, and hot-reload JARVIS plugins.

v1 plugins are plain subdirectories of ``plugins/`` (NOT separate git repos).
A plugin is any folder containing ``plugin.toml``. The manager:

  * scans ``plugins/<name>/`` for ``plugin.toml``
  * validates the manifest with pydantic
  * imports ``<entry>`` as a module and calls ``setup(api)``
  * watches each plugin dir for mtime/content changes -> teardown + reload
    WITHOUT restarting the whole process.

Hot-reload is safe for in-flight conversations because the kernel hands the
agent loop a *snapshot* of the tool table per turn; changes only affect the
next turn.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .types import KernelApi


class PluginManifest(BaseModel):
    name: str
    kind: str  # provider | memory | channel | config | tool
    version: str = "0.0.0"
    entry: str = "plugin.py"
    hot_reload: bool = True
    dependencies: list[str] = Field(default_factory=list)
    provides: dict[str, list[str]] = Field(default_factory=dict)


class Plugin:
    def __init__(self, path: Path, manifest: PluginManifest) -> None:
        self.path = path
        self.manifest = manifest
        self.name = manifest.name
        self.module: Any = None
        self._last_signature: str = ""

    def signature(self) -> str:
        """Content fingerprint for change detection (sha256 of .py/.toml bytes).

        A content hash (rather than mtime+size) reliably detects same-second,
        same-size edits on coarse-granularity filesystems.
        """
        h = hashlib.sha256()
        for root, _dirs, files in os.walk(self.path):
            for f in sorted(files):
                if f.endswith((".py", ".toml")):
                    fp = Path(root) / f
                    try:
                        h.update(fp.read_bytes())
                    except OSError:
                        pass
        return h.hexdigest()


class PluginManager:
    def __init__(self, plugins_dir: Path, kernel: Any) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.kernel = kernel
        self.plugins: dict[str, Plugin] = {}
        self._load_errors: dict[str, str] = {}

    def discover(self) -> list[Plugin]:
        found: list[Plugin] = []
        if not self.plugins_dir.exists():
            return found
        for child in sorted(self.plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            toml_path = child / "plugin.toml"
            if not toml_path.exists():
                continue
            try:
                data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                manifest = PluginManifest.model_validate(data["plugin"])
            except Exception as exc:  # noqa: BLE001
                self._load_errors[child.name] = f"manifest invalid: {exc}"
                continue
            found.append(Plugin(child, manifest))
        return found

    def install_sources(self, sources_toml: str = "plugin-sources.toml") -> list[str]:
        """Bootstrap: clone every repo listed in ``plugin-sources.toml``.

        Each entry is [source.<name>] git = "..." . Already-cloned plugins are
        fast-forward pulled. Returns the list of plugin names now present.
        """
        from .install import clone_plugin

        p = Path(sources_toml)
        if not p.exists():
            return []
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._load_errors["_sources"] = f"sources invalid: {exc}"
            return []
        names: list[str] = []
        for key, val in data.get("source", {}).items():
            git_url = val.get("git") if isinstance(val, dict) else None
            if not git_url:
                continue
            name = clone_plugin(git_url, str(self.plugins_dir), name=key)
            names.append(name)
        return names

    def load_all(self) -> None:
        for plugin in self.discover():
            self.plugins[plugin.name] = plugin
            self._load_plugin(plugin)

    def _load_plugin(self, plugin: Plugin) -> bool:
        try:
            self.kernel._set_active(plugin.name)
            spec = importlib.util.spec_from_file_location(
                f"jarvis_plugin_{plugin.name}",
                plugin.path / plugin.manifest.entry,
            )
            if spec is None or spec.loader is None:
                raise ImportError("cannot build import spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "setup"):
                raise ImportError("plugin has no setup()")
            module.setup(KernelApi(self.kernel))
            plugin.module = module
            plugin._last_signature = plugin.signature()
            self._load_errors.pop(plugin.name, None)
            return True
        except Exception as exc:  # noqa: BLE001
            self._load_errors[plugin.name] = str(exc)
            return False

    def reload(self, name: str) -> bool:
        """teardown + reload a single plugin. Safe (no full restart)."""
        plugin = self.plugins.get(name)
        if plugin is None or not plugin.manifest.hot_reload:
            return False
        module = plugin.module
        if module is not None and hasattr(module, "teardown"):
            try:
                module.teardown(KernelApi(self.kernel))
            except Exception:  # noqa: BLE001
                pass
        self.kernel._unregister_plugin(name)
        ok = self._load_plugin(plugin)
        return ok

    def check_hot_reload(self) -> list[str]:
        """Find plugins whose content changed; reload them. Returns reloaded names."""
        reloaded: list[str] = []
        for name, plugin in list(self.plugins.items()):
            if not plugin.manifest.hot_reload:
                continue
            sig = plugin.signature()
            if sig != plugin._last_signature:
                if self.reload(name):
                    reloaded.append(name)
        return reloaded

    def load_one(self, name: str) -> "Plugin | None":
        """Load a single plugin that has just appeared on disk (e.g. cloned).

        Matches by **directory name** (what clone_plugin creates), not the
        manifest's internal name — they can legitimately differ. Returns the
        loaded Plugin, or None if not found.
        """
        if name in self.plugins:
            self.reload(name)
            return self.plugins[name]
        for plugin in self.discover():
            if plugin.path.name == name:
                self.plugins[plugin.name] = plugin
                self._load_plugin(plugin)
                return plugin
        return None
