"""plugin-self: the assistant's self-awareness.

Two surfaces:

1. A **system-prompt service** (kind="self"). The kernel injects a freshly
   generated identity + capability summary into every provider request, so
   JARVIS *knows* who it is and what it can do without having to remember to
   query — hot-reload and freshly installed plugins are reflected on the very
   next turn. The prompt is rebuilt each round, never persisted, and lists
   tool *names* only: full descriptions already travel in the tools payload,
   so repeating them here would waste tokens.
2. **self.* tools** the LLM (and users) can call for detail on demand:
   self.whoami / self.capabilities / self.version / self.config.

All state is read live from KernelApi.snapshot(), so answers are always
current. Secrets are redacted from the config view.
"""
from __future__ import annotations

from jarvis.types import KernelApi


def setup(kernel: KernelApi) -> None:
    class _SelfService:
        kind = "self"

        def system_prompt(self) -> str:
            """Compact identity + capability summary for a provider request."""
            s = kernel.snapshot()
            model = s["model"] or "(default)"
            plugin_names = ", ".join(p["name"] for p in s["plugins"]) or "(none)"
            tool_names = ", ".join(t["name"] for t in s["tools"]) or "(none)"
            return (
                "You are JARVIS, a microkernel AI assistant where everything is a plugin. "
                f"Kernel: microkernel v1, plugin spec v1.0. Provider: {s['provider']} (model: {model}). "
                f"Loaded plugins ({s['n_plugins']}): {plugin_names}. "
                f"Callable tools ({s['n_tools']}): {tool_names}. "
                "Each tool\'s purpose and parameters are described in your tools list; call the right one "
                "instead of guessing. Use self.capabilities for the full inventory with descriptions, "
                "self.config for config keys, and mem.recall to revisit remembered facts. "
                "When modifying files, use the fs.* tools - they sign your edits with your "
                "identity (config [agent-identity]) for traceability."
            )

    kernel.service("self", _SelfService())

    @kernel.tool(
        "self.whoami",
        "Describe who/what JARVIS is right now: identity, architecture, provider, model, counts",
    )
    def whoami() -> str:
        s = kernel.snapshot()
        model = s["model"] or "(default)"
        memory_note = ""
        if any(t["name"] == "mem.recall" for t in s["tools"]):
            memory_note = " I have cross-session memory: you can ask me to remember things."
        return (
            "I am JARVIS, a microkernel AI assistant where everything is a "
            "plugin. The kernel itself does almost nothing — providers, memory, "
            "channels, config and tools are all plugins. "
            f"Currently loaded: {s['n_plugins']} plugins, {s['n_tools']} tools. "
            f"Active model provider: {s['provider']} (model={model}). "
            f"Config keys set: {len(s['config_keys'])}." + memory_note + " "
            "I can hot-reload any capability without restarting."
        )

    @kernel.tool(
        "self.capabilities",
        "List all currently callable tools with their descriptions — use this when deciding which tool fits a request",
    )
    def capabilities() -> str:
        s = kernel.snapshot()
        lines = ["JARVIS loaded plugins:"]
        for p in s["plugins"]:
            lines.append(f"- {p['name']} [{p['kind']}]")
        lines.append("")
        lines.append("Callable tools (name: description):")
        for t in s["tools"]:
            lines.append(f"  - {t['name']}: {t['description'] or '(no description)'}")
        if any(t["name"] == "mem.recall" for t in s["tools"]):
            lines.append("")
            lines.append("Cross-session memory: mem.store / mem.recall / mem.forget let me remember facts across sessions.")
        return "\n".join(lines)

    @kernel.tool("self.version", "Report JARVIS kernel and plugin spec versions")
    def version() -> str:
        return (
            "JARVIS microkernel: v1 (per-repo). Plugin spec: v1.0 (frozen). "
            "Architecture: everything-is-a-plugin microkernel with hot-reload."
        )

    @kernel.tool(
        "self.config",
        "Show which configuration keys are set (secrets like api keys and tokens are redacted)",
    )
    def config() -> str:
        s = kernel.snapshot()
        keys = s.get("config_keys", [])
        if not keys:
            return "(no configuration set)"
        return "Configured keys: " + ", ".join(keys)


def teardown(kernel: KernelApi) -> None:
    pass
