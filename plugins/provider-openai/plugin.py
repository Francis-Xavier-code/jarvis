"""provider-openai: an OpenAI-compatible LLM provider (the JARVIS "brain").

This is the real model provider. It speaks the OpenAI Chat Completions API, so
it works against ANY OpenAI-compatible endpoint — which is exactly what an
"aggregator" service is. The default configured vendor is **opencodego**
(one API key, many underlying vendors: minimax / kimi / glm / deepseek / qwen /
...), but swapping the base URL points the same plugin at OpenAI, a local
llama.cpp server, etc.

Reads from config (via the config-core plugin) or env vars:
  - openai_base_url  / OPENAI_BASE_URL   e.g. https://opencode.ai/zen/go/v1
  - openai_api_key   / OPENAI_API_KEY
  - model            / MODEL              default model id to request

Tool calling is supported: the kernel passes ToolSpecs; this provider forwards
them as OpenAI `tools` and yields a ChatChunk(tool_call=...) for each function
call the model emits. Tool results are fed back as `role: "tool"` messages
(carrying the matching tool_call_id, which the kernel does not track for us).

Depends on `requests` — soft-imported so the plugin loads even before the user
installs it; a clear error is returned if a chat is attempted without it.
"""
from __future__ import annotations

import json
import os
import uuid

try:
    import requests  # soft dependency
except ImportError:  # pragma: no cover
    requests = None

from jarvis.types import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    KernelApi,
    ToolCall,
)

DEFAULT_BASE = "https://opencode.ai/zen/go/v1"


class OpenAIProvider:
    kind = "provider"

    def __init__(self, kernel: KernelApi) -> None:
        self._kernel = kernel

    # ---- config helpers ----
    def _cfg(self, key: str, env: str, default: str = "") -> str:
        val = self._kernel.config.get(key, "")
        if not val:
            val = os.environ.get(env, "")
        return val or default

    def _base(self) -> str:
        return self._cfg("openai_base_url", "OPENAI_BASE_URL", DEFAULT_BASE).rstrip("/")

    def _key(self) -> str:
        return self._cfg("openai_api_key", "OPENAI_API_KEY", "")

    def _model(self) -> str:
        # aggregator does not have gpt-4o-mini; fall back to a cheap, fast model.
        return self._cfg("model", "MODEL", "deepseek-v4-flash")

    # ---- conversion: kernel ChatMessage -> openai message ----
    def _to_openai_messages(self, messages: list[ChatMessage]) -> list[dict]:
        """Convert kernel history to OpenAI messages.

        The kernel now stores an assistant turn's tool_calls on the
        ChatMessage (role="assistant", tool_calls=[...]), so we replay them
        verbatim. Tool results arrive as ChatMessage(role="tool", name=...) and
        are forwarded with the matching tool_call_id taken from the preceding
        assistant message's tool_calls.
        """
        out: list[dict] = []
        for m in messages:
            if m.role == "tool":
                # find the tool_call_id from the assistant turn that produced it
                tcid = ""
                for prev in out:
                    if prev.get("role") == "assistant" and prev.get("tool_calls"):
                        for tc in prev["tool_calls"]:
                            if tc.get("function", {}).get("name") == m.name:
                                tcid = tc.get("id", "")
                out.append(
                    {"role": "tool", "name": m.name, "content": m.content, "tool_call_id": tcid}
                )
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": m.tool_calls,
                        "reasoning_content": m.reasoning_content or "",
                    }
                )
            elif m.role == "assistant":
                # plain assistant turn (no tool calls) — still echo reasoning
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content,
                        "reasoning_content": m.reasoning_content or "",
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _to_openai_tools(self, tools) -> list[dict]:
        self._name_map = {}  # real_name <-> wire_name (dots not allowed upstream)
        out = []
        for t in tools:
            wire = t.name.replace(".", "_")
            self._name_map[t.name] = wire
            self._name_map[wire] = t.name
            params = t.parameters or {}
            # Some plugins register only the `properties` map; OpenAI requires a
            # full schema with type:"object". Normalise defensively.
            if not isinstance(params, dict) or params.get("type") != "object":
                params = {"type": "object", "properties": params if isinstance(params, dict) else {}}
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": wire,
                        "description": t.description or "",
                        "parameters": params,
                    },
                }
            )
        return out

    # ---- the chat generator (sync, per PLUGIN_SPEC §5) ----
    def chat(self, req: ChatRequest):
        if requests is None:
            yield ChatChunk(text="[provider-openai] missing dependency: pip install requests")
            return

        base = self._base()
        key = self._key()
        if not key:
            yield ChatChunk(text="[provider-openai] no API key (set openai_api_key / OPENAI_API_KEY)")
            return

        model = req.model or self._model()
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload: dict = {
            "model": model,
            "messages": self._to_openai_messages(req.messages),
            "stream": False,
        }
        tools = self._to_openai_tools(req.tools)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = None
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=120)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    continue
            if resp is None:
                yield ChatChunk(text=f"[provider-openai] request failed: {last_exc}")
                return
        except Exception as exc:  # noqa: BLE001
            yield ChatChunk(text=f"[provider-openai] request failed: {exc}")
            return

        if resp.status_code != 200:
            yield ChatChunk(text=f"[provider-openai] HTTP {resp.status_code}: {resp.text[:400]}")
            return

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        raw_calls = msg.get("tool_calls") or []

        if content:
            yield ChatChunk(text=content)
        if reasoning:
            yield ChatChunk(reasoning=reasoning)

        for tc in raw_calls:
            fn = tc.get("function", {})
            wire = fn.get("name", "")
            name = self._name_map.get(wire, wire)  # restore dotted real name
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            yield ChatChunk(tool_call=ToolCall(name=name, arguments=args))

        yield ChatChunk(done=True)


def setup(kernel: KernelApi) -> None:
    kernel.service("provider", OpenAIProvider(kernel))


def teardown(kernel: KernelApi) -> None:
    pass
