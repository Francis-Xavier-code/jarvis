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
        # stamp owner so reload can unregister precisely
        try:
            setattr(impl, "_jarvis_plugin", plugin)
        except Exception:  # noqa: BLE001
            pass
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
        # Remove services owned by this plugin. Services are keyed by kind; we
        # only clear the entry if it currently belongs to this plugin. Other
        # plugins' services are left untouched (their setup re-registers them
        # on their own reload).
        for kind, impl in list(self._services.items()):
            owner = getattr(impl, "_jarvis_plugin", None)
            if owner == name:
                self._services.pop(kind, None)
                if kind == "memory":
                    self._memory_svc = None
                elif kind == "provider":
                    self._provider_svc = None
                elif kind == "channel":
                    self._channels = [c for c in self._channels if getattr(c, "_jarvis_plugin", None) != name]

    def _rebuild_services(self) -> None:
        # No longer used for single-plugin reload; kept for full reloads if needed.
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

    def start_hot_reload_watcher(self, interval: float = 1.0) -> None:
        """Start a background thread that auto-reloads changed plugins.

        Replaces the manual ``run_hot_reload_check()``; the kernel now watches
        plugin directories continuously without any process restart.
        """
        if getattr(self, "_watcher_thread", None) is not None:
            return
        import threading

        self._watcher_active = True
        self._watcher_interval = interval

        def _loop() -> None:
            import time

            while getattr(self, "_watcher_active", False):
                try:
                    self.manager.check_hot_reload()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(self._watcher_interval)

        t = threading.Thread(target=_loop, name="jarvis-hotreload", daemon=True)
        t.start()
        self._watcher_thread = t

    def stop_hot_reload_watcher(self) -> None:
        self._watcher_active = False
        self._watcher_thread = None

    # ---- runtime plugin control (used by the install tool + CLI install) ----
    def install_plugin(self, git_url: str, name: str | None = None) -> str:
        """Clone a repo into plugins/, then hot-load it. Returns the plugin name."""
        from .install import clone_plugin

        dir_name = clone_plugin(git_url, self.plugins_dir, name=name)
        plugin = self.manager.load_one(dir_name)
        if plugin is None:
            return dir_name
        return plugin.name

    def uninstall_plugin(self, name: str) -> bool:
        # resolve by manifest name OR directory name
        plugin = self.manager.plugins.get(name)
        if plugin is None:
            for p in self.manager.plugins.values():
                if p.path.name == name or p.name == name:
                    plugin = p
                    break
        if plugin is None:
            return False
        module = plugin.module
        if module is not None and hasattr(module, "teardown"):
            try:
                module.teardown(KernelApi(self))
            except Exception:  # noqa: BLE001
                pass
        self._unregister_plugin(plugin.name)
        self.manager.plugins.pop(plugin.name, None)
        return True

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

        # Agent loop: run provider, resolve any tool calls by feeding results
        # back, repeat until a turn yields no tool calls (or hits max rounds).
        MAX_ROUNDS = 4
        for _ in range(MAX_ROUNDS):
            reply_text = ""
            reasoning_text = ""
            pending_calls: list[ToolCall] = []
            for chunk in provider.chat(req):
                if chunk.text:
                    reply_text += chunk.text
                if chunk.reasoning:
                    reasoning_text += chunk.reasoning
                if chunk.tool_call:
                    pending_calls.append(chunk.tool_call)
            if not pending_calls:
                break
            # Store the assistant turn WITH its tool_calls so the history can be
            # replayed verbatim for providers that require tool_call_id binding.
            assistant_tool_calls = [
                {
                    "id": f"call_{i}_{abs(hash(c.name)) % 100000}",
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                }
                for i, c in enumerate(pending_calls)
            ]
            history.append(
                ChatMessage(
                    role="assistant",
                    content=reply_text,
                    tool_calls=assistant_tool_calls,
                    reasoning_content=reasoning_text or None,
                )
            )
            for call in pending_calls:
                result = self._invoke_tool(call)
                history.append(
                    ChatMessage(role="tool", content=result, name=call.name)
                )
            req = ChatRequest(
                messages=history,
                tools=self.tools_snapshot(),
                model=self._config.get("model", ""),
            )

        if memory is not None:
            _user_msg = ChatMessage(role="user", content=user_text)
            _asst_msg = ChatMessage(
                role="assistant",
                content=reply_text,
                reasoning_content=reasoning_text or None,
            )
            memory.append(session, _user_msg)
            memory.append(session, _asst_msg)
        return reply_text

    def _invoke_tool(self, call: ToolCall) -> str:
        spec = self._tools.get(call.name)
        if spec is None or spec.handler is None:
            return f"[error] unknown tool: {call.name}"
        try:
            return str(spec.handler(**call.arguments))
        except Exception as exc:  # noqa: BLE001
            return f"[error] {call.name} failed: {exc}"
