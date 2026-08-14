"""plugin-self: the assistant's self-awareness.

Exposes tools the LLM (and users) can call to learn what JARVIS *is* and what
it can currently do. This is the "who am I" surface — it reads the live kernel
state (loaded plugins, registered tools) so the answer is always current, even
after hot-reload or a freshly installed plugin.

Tools:
  self.whoami      -> short identity blurb (name, architecture, model)
  self.capabilities -> list currently-loaded plugins and their tools
  self.version     -> kernel + plugin spec versions
"""
from __future__ import annotations

from jarvis.types import KernelApi


def setup(kernel: KernelApi) -> None:
    @kernel.tool("self.whoami", "Describe who/what JARVIS is right now")
    def whoami() -> str:
        k = kernel._kernel  # type: ignore[attr-defined]
        provider = k._provider_svc
        prov = type(provider).__name__ if provider is not None else "none"
        model = k._config.get("model", "") or "(default)"
        n_plugins = len(k.manager.plugins)
        n_tools = len(k._tools)
        return (
            "I am JARVIS, a microkernel AI assistant where everything is a "
            "plugin. The kernel itself does almost nothing — providers, memory, "
            "channels, config and tools are all plugins. "
            f"Currently loaded: {n_plugins} plugins, {n_tools} tools. "
            f"Active model provider: {prov} (model={model}). "
            "I can hot-reload any capability without restarting."
        )

    @kernel.tool("self.capabilities", "List what JARVIS can currently do")
    def capabilities() -> str:
        k = kernel._kernel  # type: ignore[attr-defined]
        lines = ["Loaded plugins and the tools/services they expose:"]
        for name, plugin in sorted(k.manager.plugins.items()):
            kind = plugin.manifest.kind
            provides = plugin.manifest.provides or {}
            tools = provides.get("tools", [])
            extra = f" (tools: {', '.join(tools)})" if tools else ""
            lines.append(f"- {name} [{kind}]{extra}")
        lines.append("")
        lines.append("All tools currently in the routing table:")
        for tname in sorted(k._tools.keys()):
            lines.append(f"  - {tname}")
        return "\n".join(lines)

    @kernel.tool("self.version", "Report JARVIS kernel and spec versions")
    def version() -> str:
        return (
            "JARVIS microkernel: v1 (per-repo). Plugin spec: v1.0 (frozen). "
            "Architecture: everything-is-a-plugin microkernel with hot-reload."
        )


def teardown(kernel: KernelApi) -> None:
    pass
