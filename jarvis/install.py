"""Plugin puller: turn any git repo with a plugin.toml into a JARVIS plugin.

This is the bridge between "someone else's repo" and "a JARVIS plugin". Because
the cloned directory follows the same plugin.toml convention, the existing
PluginManager.discover/load/hot-reload machinery picks it up with zero special
handling — that is the "compatible with registered plugins" property.

Two entry points use this:
  * bootstrap  -> install_sources() clones every entry in plugin-sources.toml
                  (the "default-pack a clone" behaviour)
  * install    -> install_from_url() clones one repo on demand (CLI or tool)
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(cwd: str, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _default_name(git_url: str) -> str:
    name = git_url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def clone_plugin(git_url: str, plugins_dir: str, name: str | None = None) -> str:
    """Clone ``git_url`` into ``plugins_dir/<name>``.

    If already present, attempt a fast-forward pull (best-effort). Returns the
    plugin name used.
    """
    if name is None:
        name = _default_name(git_url)
    target = Path(plugins_dir) / name
    if target.exists():
        try:
            _git(str(target), ["pull", "--ff-only"])
        except subprocess.CalledProcessError:
            # shallow/diverged clone — leave as-is, don't fail bootstrap
            pass
        return name
    Path(plugins_dir).mkdir(parents=True, exist_ok=True)
    _git(str(plugins_dir), ["clone", "--depth", "1", git_url, str(target)])
    # mark as cloned so it is gitignored and never committed as source
    (target / ".jarvis-cloned").write_text(git_url)
    return name
