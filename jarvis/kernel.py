"""The JARVIS microkernel.

Responsibilities (and NOTHING else):
  * hold the global tool table + service registry (rebuilt on plugin reload)
  * run the agent loop: memory.load -> provider.chat(stream) -> on tool_call
    route to the plugin handler -> feed result back -> memory.append
  * expose a per-turn *snapshot* of tools so hot-reload never breaks a running turn
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .plugin import PluginManager
from .types import (
    ChatMessage,
    ChatRequest,
    ConfigApi,
    KernelApi,
    ToolCall,
    ToolSpec,
)


class Kernel:
    def __init__(self, plugins_dir: str, data_dir: str) -> None:
        self.plugins_dir = plugins_dir
        self.data_dir = data_dir
        self._tools: dict[str, ToolSpec] = {}
        self._services: dict[str, Any] = {}  # kind -> impl
        self._active_plugin: str | None = None
        self._config: dict[str, Any] = {}
        self._config_watchers: dict[str, list[Callable[[str, Any], None]]] = {}
        self.config_api = ConfigApi(self)
        self.manager = PluginManager(plugins_dir, self)
        self._memory_svc: Any = None
        self._provider_svc: Any = None
        self._channels: list[Any] = []

    # ---- plugin registration hooks (called by KernelApi) ----
    def _set_active(self, name: str) -> None:
        self._active_plugin = name

    def _register_tool(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def _register_service(self, kind: str, impl: Any, plugin: str | None) -> None:
        self._services[kind] = impl
        if kind == "memory":
            self._memory_svc = impl
        elif kind == "provider":
            self._provider_svc = impl
        elif kind == "channel":
            self._channels.append(impl)

    def _unregister_plugin(self, name: str) -> None:
        for tname in [k for k, v in self._tools.items() if v.plugin == name]:
            self._tools.pop(tname, None)
        # drop services owned by this plugin (best-effort: rebuild from manager)
        self._rebuild_services()

    def _rebuild_services(self) -> None:
        self._services.clear()
        self._memory_svc = None
        self._provider_svc = None
        self._channels = []
        for plugin in self.manager.plugins.values():
            if plugin.module is not None and hasattr(plugin.module, "register_services"):
                try:
                    plugin.module.register_services(KernelApi(self))
                except Exception:  # noqa: BLE001
                    pass

    # ---- config hooks ----
    def _config_get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _config_watch(self, key: str, cb: Callable[[str, Any], None]) -> None:
        self._config_watchers.setdefault(key, []).append(cb)

    def set_config(self, data: dict[str, Any]) -> None:
        self._config = data
        for k, v in data.items():
            for cb in self._config_watchers.get(k, []):
                try:
                    cb(k, v)
                except Exception:  # noqa: BLE001
                    pass

    # ---- public surface ----
    def load(self) -> None:
        self.manager.load_all()
        # config plugin seeds the kernel config if present
        cfg = self._services.get("config")
        if cfg is not None and hasattr(cfg, "snapshot"):
            self.set_config(cfg.snapshot())

    def tools_snapshot(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def run_hot_reload_check(self) -> list[str]:
        return self.manager.check_hot_reload()

    # ---- agent loop ----
    def chat(self, session: str, user_text: str) -> str:
        """One conversation turn. Returns assistant text."""
        provider = self._provider_svc
        if provider is None:
            return "[jarvis] no provider plugin loaded"
        memory = self._memory_svc
        history: list[ChatMessage] = []
        if memory is not None:
            history = memory.load(session)
        history.append(ChatMessage(role="user", content=user_text))

        req = ChatRequest(
            messages=history,
            tools=self.tools_snapshot(),
            model=self._config.get("model", ""),
        )

        reply_text = ""
        pending_calls: list[ToolCall] = []
        for chunk in provider.chat(req):
            if chunk.text:
                reply_text += chunk.text
            if chunk.tool_call:
                pending_calls.append(chunk.tool_call)

        # execute tool calls synchronously (v1), feed results back as a 2nd pass
        if pending_calls:
            history.append(ChatMessage(role="assistant", content=reply_text))
            for call in pending_calls:
                result = self._invoke_tool(call)
                history.append(
                    ChatMessage(role="tool", content=result, name=call.name)
                )
            req2 = ChatRequest(
                messages=history, tools=self.tools_snapshot(),
                model=self._config.get("model", ""),
            )
            reply_text = ""
            for chunk in provider.chat(req2):
                if chunk.text:
                    reply_text += chunk.text

        if memory is not None:
            memory.append(session, ChatMessage(role="user", content=user_text))
            memory.append(session, ChatMessage(role="assistant", content=reply_text))
        return reply_text

    def _invoke_tool(self, call: ToolCall) -> str:
        spec = self._tools.get(call.name)
        if spec is None or spec.handler is None:
            return f"[error] unknown tool: {call.name}"
        try:
            return str(spec.handler(**call.arguments))
        except Exception as exc:  # noqa: BLE001
            return f"[error] {call.name} failed: {exc}"
