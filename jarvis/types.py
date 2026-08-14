"""Cross-plugin contracts for JARVIS.

Every capability (LLM provider, memory, channel, config, tool) is a plugin.
Plugins register themselves against a :class:`KernelApi` instance passed to
their ``setup`` hook. Tools are collected into a single name->callable table
that the agent loop routes LLM tool_calls to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

# A tool callable: receives already-parsed kwargs, returns a string result.
ToolFn = Callable[..., str]


@dataclass
class ToolSpec:
    """Metadata for a single tool exposed by a plugin."""

    name: str
    description: str
    # JSON-schema-ish parameter description; kept simple for v1.
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: ToolFn | None = None
    plugin: str | None = None


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    name: str | None = None  # tool name, when role == "tool"
    # OpenAI-style tool_calls attached to an assistant message, so the history
    # can be replayed faithfully (the kernel stores them; providers forward
    # them verbatim). Each item: {"id", "type", "function": {"name","arguments"}}.
    tool_calls: list[dict] | None = None
    # reasoning_content (deepseek thinking mode) — must be echoed back on
    # multi-turn so the upstream does not reject the request.
    reasoning_content: str | None = None


@dataclass
class ChatRequest:
    """A request handed to a provider plugin's ``chat`` hook."""

    messages: list[ChatMessage]
    tools: list[ToolSpec]
    model: str = ""


@runtime_checkable
class ChatStream(Protocol):
    """Minimal streaming response contract a provider plugin yields."""

    def __iter__(self) -> Any:
        ...


@dataclass
class ChatChunk:
    """One piece of a streamed provider response."""

    text: str | None = None
    tool_call: "ToolCall | None" = None
    reasoning: str | None = None  # deepseek-style thinking content
    done: bool = False


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


class KernelApi:
    """The surface plugins use to register tools and read config.

    A fresh instance is handed to every plugin's ``setup``. All registrations
    are recorded centrally on the owning kernel so a full teardown/reload is
    possible without losing the global tool table between plugin reloads.
    """

    def __init__(self, kernel: "Any") -> None:
        self._kernel = kernel

    def tool(self, name: str, description: str = "", parameters: dict | None = None):
        """Decorator: register a tool under ``name`` (e.g. ``hass.light_on``)."""

        def decorator(fn: ToolFn) -> ToolFn:
            self._kernel._register_tool(
                ToolSpec(
                    name=name,
                    description=description or (fn.__doc__ or "").strip(),
                    parameters=parameters or {},
                    handler=fn,
                    plugin=self._kernel._active_plugin,
                )
            )
            return fn

        return decorator

    def service(self, kind: str, impl: Any) -> None:
        """Register a kind-scoped service (provider.chat / memory.load ...)."""
        self._kernel._register_service(kind, impl, self._kernel._active_plugin)

    @property
    def config(self) -> "ConfigApi":
        return self._kernel.config_api


class PluginApi:
    """Runtime plugin control exposed to tools (e.g. jarvis.install_plugin)."""

    def __init__(self, kernel: "Any") -> None:
        self._kernel = kernel

    def install_from_url(self, git_url: str, name: str | None = None) -> str:
        return self._kernel.install_plugin(git_url, name)

    def uninstall(self, name: str) -> bool:
        return self._kernel.uninstall_plugin(name)


class ConfigApi:
    """Read/subscribe config exposed by the config plugin."""

    def __init__(self, kernel: "Any") -> None:
        self._kernel = kernel

    def get(self, key: str, default: Any = None) -> Any:
        return self._kernel._config_get(key, default)

    def watch(self, key: str, cb: Callable[[str, Any], None]) -> None:
        self._kernel._config_watch(key, cb)
