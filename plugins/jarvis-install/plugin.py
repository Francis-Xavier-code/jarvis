"""jarvis-install: the kernel's pull capability, exposed as a plugin tool.

Because "installing a plugin" is itself a capability, it lives in the plugin
system like everything else. It clones any git repo that follows the
plugin.toml convention into plugins/ and hot-loads it — no kernel restart.

Tools:
  jarvis.install_plugin(git_url, name?)  -> clones + loads, returns plugin name
  jarvis.uninstall_plugin(name)          -> tears down + removes from registry
"""
from __future__ import annotations

from jarvis.types import KernelApi, PluginApi


def setup(kernel: KernelApi) -> None:
    api = PluginApi(kernel._kernel)

    @kernel.tool(
        "jarvis.install_plugin",
        "Clone a git repo that follows the JARVIS plugin.toml convention into "
        "plugins/ and hot-load it. Returns the plugin name. Example: a "
        "jarvis-homeassistant repo becomes hass.* tools immediately.",
        {"git_url": {"type": "string"}, "name": {"type": "string"}},
    )
    def install_plugin(git_url: str, name: str = "") -> str:
        n = api.install_from_url(git_url, name or None)
        return f"installed plugin '{n}' (from {git_url})"

    @kernel.tool(
        "jarvis.uninstall_plugin",
        "Remove a loaded plugin by name.",
        {"name": {"type": "string"}},
    )
    def uninstall_plugin(name: str) -> str:
        ok = api.uninstall(name)
        return f"uninstalled '{name}'" if ok else f"plugin '{name}' not found"


def teardown(kernel: KernelApi) -> None:
    pass
