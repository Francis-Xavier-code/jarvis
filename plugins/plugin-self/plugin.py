"""plugin-self: the assistant's self-awareness.

Exposes tools the LLM (and users) can call to learn what JARVIS *is* and what
it can currently do. This is the "who am I" surface — it reads the live kernel
state via the KernelApi.snapshot() view, so the answer is always current, even
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
        s = kernel.snapshot()
        model = s["model"] or "(default)"
        return (
            "I am JARVIS, a microkernel AI assistant where everything is a "
            "plugin. The kernel itself does almost nothing — providers, memory, "
            "channels, config and tools are all plugins. "
            f"Currently loaded: {s['n_plugins']} plugins, {s['n_tools']} tools. "
            f"Active model provider: {s['provider']} (model={model}). "
            "I can hot-reload any capability without restarting."
        )

    @kernel.tool("self.capabilities", "List what JARVIS can currently do")
    def capabilities() -> str:
        s = kernel.snapshot()
        lines = ["Loaded plugins and the tools/services they expose:"]
        for p in s["plugins"]:
            tools = p["tools"]
            extra = f" (tools: {', '.join(tools)})" if tools else ""
            lines.append(f"- {p['name']} [{p['kind']}]{extra}")
        lines.append("")
        lines.append("All tools currently in the routing table:")
        for tname in s["tools"]:
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
