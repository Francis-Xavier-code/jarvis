"""The JARVIS microkernel.

Responsibilities (and NOTHING else):
  * hold the global tool table + service registry (rebuilt on plugin reload)
  * run the agent loop: memory.load -> provider.chat(stream) -> on tool_call
    route to the plugin handler -> feed result back -> memory.save/append
  * expose a per-round *snapshot* of tools so hot-reload never breaks a
    running turn (both the provider request and tool dispatch use the same
    snapshot taken at the start of the round)
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from .plugin import PluginManager
from .types import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ConfigApi,
    KernelApi,
    ToolCall,
    ToolSpec,
)

# Config keys whose values should never be surfaced to the assistant.
_SECRET_HINTS = ("api_key", "token", "secret", "password", "passwd")

# Well-known credential shapes, redacted even when not in the config.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
]

# Default conversation-rounds budget sent to the provider (older rounds are
# trimmed from the request; full history is still persisted). 0/None = no trim.
DEFAULT_MAX_ROUNDS = 30


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
        # Gate for assistant-initiated plugin installs: returning False refuses
        # the install. Defaults to an interactive terminal prompt; tests and
        # headless deployments can replace it (or set it to None to allow).
        self.confirm_install: Callable[[str], bool] | None = self._default_confirm_install
        # Generic gate for assistant-initiated actions (bash commands, out-of-
        # project file writes ...). Same interactive default as confirm_install.
        # Both gates are bypassed when config `auto_approve = true` (headless /
        # trusted setups): see auto_approve().
        self.confirm_action: Callable[[str], bool] | None = self._default_confirm_install

    def auto_approve(self) -> bool:
        """True when config ``auto_approve`` is set.

        With auto-approve on, assistant-initiated actions (bash commands,
        file writes, plugin installs) are approved automatically instead of
        prompting the user. Read live from the config, so toggling
        config.toml hot-reloads into effect without a restart.
        """
        return bool(self._config.get("auto_approve"))

    def set_auto_approve(self, on: bool) -> None:
        """Turn auto-approve on/off live, persisting it to config.toml.

        Updates the in-memory config immediately (channels can toggle it at
        runtime, e.g. the TUI's /autoapprove command) and, when the config
        plugin is loaded, writes the key through its ``set`` hook so the
        choice survives a restart.
        """
        self._config["auto_approve"] = bool(on)
        cfg = self._services.get("config")
        if cfg is not None and hasattr(cfg, "set"):
            try:
                cfg.set("auto_approve", bool(on))
            except Exception:  # noqa: BLE001 - persistence is best-effort
                pass

    def confirm(self, prompt: str) -> bool:
        """Ask the user to approve an assistant-initiated action.

        Refuses by default when no handler is configured or it errors;
        approves without prompting when config ``auto_approve`` is set.
        """
        if self.auto_approve():
            return True
        if self.confirm_action is None:
            return False
        try:
            return bool(self.confirm_action(prompt))
        except Exception:  # noqa: BLE001
            return False

    def confirm_hard(self, prompt: str) -> bool:
        """Ask the user, NEVER bypassed by ``auto_approve``.

        Used for writes to frozen paths (.jarvis-frozen): auto_approve may
        green-light bash commands or installs, but protected core files must
        always get an explicit human yes.
        """
        if self.confirm_action is None:
            return False
        try:
            return bool(self.confirm_action(prompt))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _default_confirm_install(prompt: str) -> bool:
        """Interactive y/N confirmation for assistant-initiated actions.

        The prompt starts on a fresh line so it never glues onto streaming
        output, empty/unknown answers are re-asked (so a half-typed message
        from mid-reply cannot be misread as an answer), and bare Enter = no.
        """
        try:
            while True:
                answer = input(f"\n{prompt} [y/N] ").strip().lower()
                if answer in ("y", "yes"):
                    return True
                if answer in ("", "n", "no"):
                    return False
                print("[jarvis] please answer y or N")
        except (EOFError, KeyboardInterrupt):
            return False

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

    def _state_snapshot(self) -> dict:
        """Read-only view of kernel state (for the self-awareness tools).

        ``tools`` carries each registered tool's name and description (the live
        routing table is authoritative; ``provides`` in manifests can drift).
        ``config_keys`` lists configured keys with secrets redacted, so the
        assistant can see what is set without leaking api keys / tokens.
        """
        provider = self._provider_svc
        plugins = []
        for name, p in sorted(self.manager.plugins.items()):
            provides = p.manifest.provides or {}
            plugins.append({
                "name": name,
                "kind": p.manifest.kind,
                "tools": list(provides.get("tools", [])),
            })
        tools = [
            {"name": name, "description": spec.description or ""}
            for name, spec in sorted(self._tools.items())
        ]
        config_keys = sorted(
            k for k in self._config
            if not any(h in k.lower() for h in _SECRET_HINTS)
        )
        return {
            "provider": type(provider).__name__ if provider is not None else "none",
            "model": self._config.get("model", ""),
            "n_plugins": len(self.manager.plugins),
            "n_tools": len(self._tools),
            "plugins": plugins,
            "tools": tools,
            "config_keys": config_keys,
        }

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

    def get_service(self, kind: str):
        """Public accessor for a registered plugin service (channels, tools)."""
        return self._services.get(kind)

    def history(self, session: str) -> list[ChatMessage]:
        """Load a session's persisted history (channels replay it on startup)."""
        if self._memory_svc is None:
            return []
        try:
            return self._memory_svc.load(session)
        except Exception:  # noqa: BLE001
            return []

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
        """Clone a repo into plugins/, then hot-load it. Returns the plugin name.

        Raises PluginInstallError on unsafe names / clone failures. The
        assistant-facing PluginApi wrapper adds URL + confirmation checks.
        """
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
    def chat(
        self,
        session: str,
        user_text: str,
        on_chunk: Callable[[ChatChunk], None] | None = None,
        on_tool: Callable[[ToolCall], None] | None = None,
        on_tool_done: Callable[[ToolCall, str, float], None] | None = None,
    ) -> str:
        """One conversation turn. Returns assistant text.

        Optional streaming callbacks: ``on_chunk(chunk)`` fires for every
        provider chunk as it is produced (or replayed from cache), and
        ``on_tool(call)`` fires before each tool invocation — channels use
        these to render output live instead of waiting for the full reply.

        Each round takes a fresh snapshot of the tool table; both the provider
        request and tool dispatch use that same snapshot, so a hot-reload
        mid-turn can never desynchronise the two. A failing provider is
        reported as error text instead of crashing the caller.

        If a "self" service is registered (plugin-self), its system_prompt() is
        injected at the front of every provider request — regenerated each
        round, never persisted — so the assistant always knows its identity,
        loaded plugins and callable tools without having to query for them.

        If a "cache" service is registered (cache-core), the request
        fingerprint is checked before calling the provider; on a hit the
        cached chunks replay and the provider (and its tokens) are skipped.
        Only successful responses (trailing done=True) are stored, so error
        stubs never poison the cache.
        """
        provider = self._provider_svc
        if provider is None:
            return "[jarvis] no provider plugin loaded"
        memory = self._memory_svc
        history: list[ChatMessage] = []
        if memory is not None:
            history = memory.load(session)
        old_len = len(history)
        history.append(ChatMessage(role="user", content=user_text))
        self_svc = self._services.get("self")
        persona_svc = self._services.get("personality")
        cache_svc = self._services.get("cache")
        mem_cfg = self._config.get("memory", {})
        max_rounds = (
            mem_cfg.get("max_rounds", DEFAULT_MAX_ROUNDS)
            if isinstance(mem_cfg, dict)
            else DEFAULT_MAX_ROUNDS
        )

        def _context_messages() -> list[ChatMessage]:
            """System prefix + history (trimmed to recent rounds).

            Prefix order: personality -> self-awareness -> remembered facts ->
            conversation history. Only the pre-turn history is trimmed; the
            current turn (new user message plus any tool rounds) is always
            kept intact, bounding tokens sent to the provider each round
            while the full history is still persisted.
            """
            msgs = history
            if max_rounds and old_len:
                msgs = self._trim_history(history[:old_len], max_rounds) + history[old_len:]
            prefix: list[ChatMessage] = []
            for svc in (persona_svc, self_svc):
                if svc is None:
                    continue
                try:
                    prompt = svc.system_prompt()
                except Exception:  # noqa: BLE001
                    continue
                if prompt:
                    prefix.append(ChatMessage(role="system", content=prompt))
            # remember cross-session facts, if the memory plugin exposes them
            if memory is not None and hasattr(memory, "recall_all"):
                try:
                    facts = memory.recall_all()
                except Exception:  # noqa: BLE001
                    facts = ""
                if facts:
                    prefix.append(
                        ChatMessage(role="system", content=f"Remembered facts:\n{facts}")
                    )
            return prefix + msgs

        def _provider_chunks(req: ChatRequest) -> "tuple[list[ChatChunk], bool]":
            """Provider chunks for this request, served from cache when possible.

            Returns (chunks, from_cache) so the caller can log whether the
            round hit the cache (i.e. cost no upstream tokens).
            """
            if cache_svc is not None:
                cached = cache_svc.get(req)
                if cached is not None:
                    return cached, True
            try:
                chunks = list(provider.chat(req))
            except Exception as exc:  # noqa: BLE001
                return [ChatChunk(text=f"[error] provider failed: {exc}")], False
            if cache_svc is not None:
                try:
                    cache_svc.put(req, chunks)
                except Exception:  # noqa: BLE001
                    pass
            return chunks, False

        # Tool-call round budget: one provider request per round. After the
        # budget the loop runs ONE text-only wind-down request (no tools are
        # advertised) so a multi-step task ALWAYS ends with a real final
        # answer, never a silent cutoff (config: [agent] max_tool_rounds).
        MAX_ROUNDS = 4  # default tool-call rounds per turn
        agent_cfg = self._config.get("agent", {})
        tool_rounds = (
            max(1, int(agent_cfg.get("max_tool_rounds", MAX_ROUNDS)))
            if isinstance(agent_cfg, dict)
            else MAX_ROUNDS
        )
        reply_text = ""
        reasoning_text = ""
        logger_svc = self._services.get("logger")
        rounds = 0
        total_prompt = 0
        total_completion = 0
        total_tool_calls = 0
        any_cache_hit = False
        last_model = ""
        last_round_tools = False
        for _ in range(tool_rounds + 1):  # +1 = wind-down final-answer request
            rounds += 1
            last_round_tools = False
            snapshot = self.tools_snapshot()
            tool_table = {s.name: s for s in snapshot}
            # Wind-down: advertise NO tools so the model cannot call another
            # tool and must produce the final answer text. The limit note
            # below now only fires for a provider that returns tool calls
            # anyway (broken/stub) - never a silent mid-task cutoff.
            wind_down = rounds > tool_rounds
            req = ChatRequest(
                messages=_context_messages(),
                tools=[] if wind_down else snapshot,
                model=self._config.get("model", ""),
            )
            last_model = req.model
            reply_text = ""
            reasoning_text = ""
            pending_calls: list[ToolCall] = []
            chunks, from_cache = _provider_chunks(req)
            any_cache_hit = any_cache_hit or from_cache
            for chunk in chunks:
                if on_chunk is not None:
                    try:
                        on_chunk(
                            ChatChunk(
                                text=self._redact(chunk.text) if chunk.text else None,
                                reasoning=self._redact(chunk.reasoning) if chunk.reasoning else None,
                                tool_call=chunk.tool_call,
                                done=chunk.done,
                            )
                        )
                    except Exception:  # noqa: BLE001
                        pass
                if chunk.text:
                    reply_text += self._redact(chunk.text)
                if chunk.reasoning:
                    reasoning_text += self._redact(chunk.reasoning)
                if chunk.tool_call:
                    pending_calls.append(chunk.tool_call)
            if chunks and chunks[-1].usage:
                total_prompt += int(chunks[-1].usage.get("prompt_tokens") or 0)
                total_completion += int(chunks[-1].usage.get("completion_tokens") or 0)
            total_tool_calls += len(pending_calls)
            if not pending_calls:
                break
            last_round_tools = True
            # Store the assistant turn WITH its tool_calls so the history can be
            # replayed verbatim for providers that require tool_call_id binding.
            # Prefer the provider-assigned id (threaded through ToolCall.id).
            assistant_tool_calls = [
                {
                    "id": c.id or f"call_{i}_{abs(hash(c.name)) % 100000}",
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
                if on_tool is not None:
                    try:
                        on_tool(call)
                    except Exception:  # noqa: BLE001
                        pass
                t_start = time.time()
                result = self._invoke_tool(call, tool_table)
                if on_tool_done is not None:
                    try:
                        on_tool_done(call, result, time.time() - t_start)
                    except Exception:  # noqa: BLE001
                        pass
                history.append(ChatMessage(role="tool", content=result, name=call.name))

        # Wind-down note: the +1 request above ran because the previous round
        # still called tools, and it called tools again - the task is now
        # genuinely capped. Say so explicitly instead of ending mid-task.
        if last_round_tools:
            note = (
                f"\n\n[note] tool-round limit reached ({tool_rounds}); the task may be "
                "incomplete - ask me to continue"
            )
            reply_text = (reply_text + note).strip()
            if on_chunk is not None:
                try:
                    on_chunk(ChatChunk(text=note))
                except Exception:  # noqa: BLE001
                    pass

        # Persist the final assistant reply too: text-only rounds (no tool
        # calls) never entered the loop's history.append above, so without
        # this the last answer would be missing from the saved session. The
        # model then cannot see what it already said and tends to repeat
        # itself on the next turn.
        if reply_text or reasoning_text:
            history.append(
                ChatMessage(
                    role="assistant",
                    content=reply_text,
                    reasoning_content=reasoning_text or None,
                )
            )

        if memory is not None:
            self._persist_turn(memory, session, history, user_text, reply_text, reasoning_text)
        if logger_svc is not None:
            try:
                logger_svc.log_turn({
                    "ts": time.time(),
                    "session": session,
                    "model": last_model,
                    "prompt_tokens": total_prompt,
                    "completion_tokens": total_completion,
                    "cache_hit": any_cache_hit,
                    "rounds": rounds,
                    "tool_calls": total_tool_calls,
                })
            except Exception:  # noqa: BLE001
                pass
        return reply_text

    def _persist_turn(
        self,
        memory: Any,
        session: str,
        history: list[ChatMessage],
        user_text: str,
        reply_text: str,
        reasoning_text: str,
    ) -> None:
        """Persist the turn. Prefers full-history ``save`` (keeps tool-call
        rounds and reasoning for faithful replay); falls back to appending just
        the user + final assistant message for legacy memory plugins."""
        save = getattr(memory, "save", None)
        if callable(save):
            try:
                save(session, history)
                return
            except Exception:  # noqa: BLE001
                pass  # fall through to append-based persistence
        memory.append(session, ChatMessage(role="user", content=user_text))
        memory.append(
            session,
            ChatMessage(role="assistant", content=reply_text, reasoning_content=reasoning_text or None),
        )

    def _secret_values(self) -> list[str]:
        """Sensitive config values (api keys/tokens/secrets), recursively."""
        values: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if isinstance(v, (dict, list)):
                        walk(v)
                    elif (
                        isinstance(v, str)
                        and len(v) >= 8
                        and any(h in k.lower() for h in _SECRET_HINTS)
                    ):
                        values.append(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(self._config)
        return values

    def _redact(self, text: str) -> str:
        """Mask configured secrets and known credential shapes in output.

        Applied at the output boundary (streamed chunks, final reply, and the
        persisted assistant message) so the LLM can never leak api keys or
        tokens back to the user or into later context.
        """
        if not text:
            return text
        for value in self._secret_values():
            if value and value in text:
                text = text.replace(value, "***")
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub("***", text)
        return text

    def _trim_history(self, history: list[ChatMessage], max_rounds: int) -> list[ChatMessage]:
        """Keep only the most recent ``max_rounds`` conversation rounds.

        A round starts at each user message; assistant and tool messages belong
        to the preceding user round, so tool results are never split from the
        assistant call that produced them. A system note marks the truncation.
        Trimming only affects what is sent to the provider — the persisted
        history stays complete.
        """
        if max_rounds <= 0 or len(history) <= 1:
            return history
        rounds: list[list[ChatMessage]] = []
        cur: list[ChatMessage] = []
        for m in history:
            if m.role == "user":
                if cur:
                    rounds.append(cur)
                cur = [m]
            else:
                cur.append(m)
        if cur:
            rounds.append(cur)
        if len(rounds) <= max_rounds:
            return history
        kept = rounds[-max_rounds:]
        flat = [m for r in kept for m in r]
        note = ChatMessage(
            role="system",
            content=f"[context trimmed: keeping the most recent {max_rounds} rounds]",
        )
        return [note] + flat

    def _invoke_tool(self, call: ToolCall, tool_table: dict[str, ToolSpec]) -> str:
        """Dispatch a tool call against the round's snapshot (never live tables).

        Using the snapshot means a mid-turn plugin reload cannot make an
        already-planned tool call vanish or swap to a half-loaded handler.
        """
        spec = tool_table.get(call.name)
        if spec is None or spec.handler is None:
            return f"[error] unknown tool: {call.name}"
        try:
            return str(spec.handler(**call.arguments))
        except Exception as exc:  # noqa: BLE001
            return f"[error] {call.name} failed: {exc}"

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 02:47:51 ---
