"""Plugin puller: turn any git repo with a plugin.toml into a JARVIS plugin.

This is the bridge between "someone else's repo" and "a JARVIS plugin". Because
the cloned directory follows the same plugin.toml convention, the existing
PluginManager.discover/load/hot-reload machinery picks it up with zero special
handling — that is the "compatible with registered plugins" property.

Two entry points use this:
  * bootstrap  -> install_sources() clones every entry in plugin-sources.toml
                  (the "default-pack a clone" behaviour)
  * install    -> install_from_url() clones one repo on demand (CLI or tool)

Security: clone targets are hardened. Directory names are validated against a
whitelist (no path traversal) and git subprocesses run with a timeout. The
assistant-facing entry point (PluginApi.install_from_url) additionally refuses
non-http(s) URLs and requires explicit user confirmation.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# git clone can block forever on a stalled network; bound every subprocess.
GIT_TIMEOUT_SECONDS = 60

# Only [A-Za-z0-9_-] (and must start alnum) — blocks "../", "/", and weird names.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class PluginInstallError(RuntimeError):
    """Raised when cloning/updating a plugin repo fails or is refused."""


def _safe_name(name: str) -> str:
    if not _SAFE_NAME_RE.match(name):
        raise PluginInstallError(
            f"unsafe plugin name {name!r}: only letters, digits, '-' and '_' are allowed"
        )
    return name


def _git(cwd: str, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def _default_name(git_url: str) -> str:
    name = git_url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def clone_plugin(git_url: str, plugins_dir: str, name: str | None = None) -> str:
    """Clone ``git_url`` into ``plugins_dir/<name>``.

    If already present, attempt a fast-forward pull (best-effort). Returns the
    plugin name used. Raises :class:`PluginInstallError` on unsafe names or
    clone/pull failures. The assistant-facing entry point additionally enforces
    http(s)-only URLs and user confirmation (see PluginApi.install_from_url).
    """
    if name is None:
        name = _default_name(git_url)
    name = _safe_name(name)
    target = Path(plugins_dir) / name
    if target.exists():
        try:
            _git(str(target), ["pull", "--ff-only"])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # shallow/diverged clone — leave as-is, don't fail bootstrap
            pass
        return name
    Path(plugins_dir).mkdir(parents=True, exist_ok=True)
    try:
        _git(str(plugins_dir), ["clone", "--depth", "1", git_url, str(target)])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise PluginInstallError(f"git clone failed for {git_url!r}: {exc}") from exc
    # mark as cloned so it is gitignored and never committed as source
    (target / ".jarvis-cloned").write_text(git_url)
    return name
