"""personality: a configurable persona for the assistant.

Registers a `personality` service whose system_prompt() is injected ahead of
the self-awareness prompt on every provider request, so the assistant has a
stable voice and manner regardless of model/provider. Hot-editing config.toml
or this file re-shapes the persona on the next turn (no restart).

Config (config.toml [personality] section):
  name    = "JARVIS"
  style   = "concise, warm, a little playful; emoji sparingly"
  traits  = "helpful, precise, honest about limits"
  rules   = "never claim to have done something you have not done"
"""
from __future__ import annotations

from jarvis.types import KernelApi

DEFAULTS = {
    "name": "JARVIS",
    "style": "concise, warm, a little playful; use emoji sparingly",
    "traits": "helpful, precise, self-aware of being a plugin-based assistant",
    "rules": "be honest about limits; say when you would need a tool or plugin you do not have",
}


def _pick(cfg: dict, key: str) -> str:
    val = cfg.get(key) if isinstance(cfg, dict) else None
    return str(val).strip() if val else DEFAULTS[key]


def setup(kernel: KernelApi) -> None:
    class _PersonalityService:
        kind = "personality"

        def system_prompt(self) -> str:
            cfg = kernel.config.get("personality", {}) or {}
            name = _pick(cfg, "name")
            style = _pick(cfg, "style")
            traits = _pick(cfg, "traits")
            rules = _pick(cfg, "rules")
            lines = [
                f"You are {name}, a microkernel AI assistant where everything is a plugin.",
                f"Style: {style}",
                f"Traits: {traits}",
                f"Rules: {rules}",
            ]
            return "\n".join(lines)

    kernel.service("personality", _PersonalityService())


def teardown(kernel: KernelApi) -> None:
    pass
