"""plugin-self: the assistant's self-awareness.

Two surfaces:

1. A **system-prompt service** (kind="self"). The kernel injects a freshly
   generated identity + capability summary into every provider request, so
   JARVIS *knows* who it is and what it can do without having to remember to
   query — hot-reload and freshly installed plugins are reflected on the very
   next turn. The prompt is rebuilt each round and never persisted.
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
            """One-shot identity + capability summary for a provider request."""
            s = kernel.snapshot()
            model = s["model"] or "(default)"
            plugin_names = ", ".join(p["name"] for p in s["plugins"]) or "(none)"
            lines = [
                "You are JARVIS, a microkernel AI assistant where everything is a plugin.",
                f"Kernel: microkernel v1, plugin spec v1.0. Provider: {s['provider']} (model: {model}).",
                f"Loaded plugins ({s['n_plugins']}): {plugin_names}.",
                "Available tools — call the right one instead of guessing:",
            ]
            for t in s["tools"]:
                lines.append(f"- {t['name']}: {t['description'] or '(no description)'}")
            lines.append("For detail not listed here, call self.capabilities or self.config.")
            return "\n".join(lines)

    kernel.service("self", _SelfService())

    @kernel.tool(
        "self.whoami",
        "Describe who/what JARVIS is right now: identity, architecture, provider, model, counts",
    )
    def whoami() -> str:
        s = kernel.snapshot()
        model = s["model"] or "(default)"
        return (
            "I am JARVIS, a microkernel AI assistant where everything is a "
            "plugin. The kernel itself does almost nothing — providers, memory, "
            "channels, config and tools are all plugins. "
            f"Currently loaded: {s['n_plugins']} plugins, {s['n_tools']} tools. "
            f"Active model provider: {s['provider']} (model={model}). "
            f"Config keys set: {len(s['config_keys'])}. "
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
