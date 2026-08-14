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
  - stream           / JARVIS_STREAM      true (default) = SSE streaming, first
                         token renders as soon as the upstream produces it;
                         false = buffered non-streaming fallback

Tool calling is supported: the kernel passes ToolSpecs; this provider forwards
them as OpenAI `tools` and yields a ChatChunk(tool_call=...) for each function
call the model emits. Tool results are fed back as `role: "tool"` messages with
the exact tool_call_id of the assistant turn that produced them (paired in
history order), and tool names are mapped to dot-free wire names on every
outbound message so multi-round replay is consistent.

Depends on `requests` — soft-imported so the plugin loads even before the user
installs it; a clear error is returned if a chat is attempted without it.
"""
from __future__ import annotations

import json
import os

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
        self._name_map: dict[str, str] = {}

    # ---- config helpers ----
    def _cfg(self, key: str, env: str, default: str = "") -> str:
        # config.toml groups this plugin's settings under [provider-openai]
        val = self._kernel.config.get(f"provider-openai.{key}", "")
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

    # ---- tool-name mapping (dots are not allowed upstream) ----
    def _ensure_name_map(self, tools) -> None:
        """Build real_name <-> wire_name for every tool in the snapshot."""
        self._name_map = {}
        for t in tools:
            wire = t.name.replace(".", "_")
            self._name_map[t.name] = wire
            self._name_map[wire] = t.name

    def _wire_name(self, name: str) -> str:
        return self._name_map.get(name, name)

    # ---- conversion: kernel ChatMessage -> openai message ----
    def _to_openai_messages(self, messages: list[ChatMessage]) -> list[dict]:
        """Convert kernel history to OpenAI messages.

        Assistant tool_calls are replayed with dot-free wire names (matching the
        tools advertised in this request), and each role="tool" result is bound
        to the tool_call_id of the assistant call that produced it — paired in
        history order rather than by name, so repeated calls to the same tool
        never get cross-wired. reasoning_content is only echoed when non-empty,
        so endpoints without deepseek-style thinking accept the payload.
        """
        out: list[dict] = []
        pending_ids: list[str] = []
        for m in messages:
            if m.role == "tool":
                tcid = pending_ids.pop(0) if pending_ids else ""
                out.append(
                    {
                        "role": "tool",
                        "name": self._wire_name(m.name or ""),
                        "content": m.content,
                        "tool_call_id": tcid,
                    }
                )
            elif m.role == "assistant" and m.tool_calls:
                calls = []
                for tc in m.tool_calls:
                    fn = dict(tc.get("function", {}))
                    fn["name"] = self._wire_name(fn.get("name", ""))
                    calls.append({**tc, "function": fn})
                    tcid = tc.get("id")
                    if tcid:
                        pending_ids.append(tcid)
                msg: dict = {"role": "assistant", "content": m.content or None, "tool_calls": calls}
                if m.reasoning_content:
                    msg["reasoning_content"] = m.reasoning_content
                out.append(msg)
            elif m.role == "assistant":
                # plain assistant turn (no tool calls) — echo reasoning if any
                msg = {"role": "assistant", "content": m.content}
                if m.reasoning_content:
                    msg["reasoning_content"] = m.reasoning_content
                out.append(msg)
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _to_openai_tools(self, tools) -> list[dict]:
        # name map was already built by _ensure_name_map(req.tools) in chat()
        out = []
        for t in tools:
            wire = self._name_map.get(t.name, t.name.replace(".", "_"))
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

    # ---- the chat generator (sync generator, per PLUGIN_SPEC §5) ----
    # True streaming: the request uses stream=true and the Server-Sent-Events
    # response is parsed event by event, so the first token arrives as soon as
    # the upstream produces it. Tool-call arguments arrive split across events
    # and are accumulated per index. Set [provider-openai] stream=false to use
    # the non-streaming fallback instead.
    def _stream_enabled(self) -> bool:
        v = self._cfg("stream", "JARVIS_STREAM", "true")
        return str(v).strip().lower() in ("1", "true", "yes", "on")

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
        self._ensure_name_map(req.tools)
        stream = self._stream_enabled()

        try:
            payload: dict = {
                "model": model,
                "messages": self._to_openai_messages(req.messages),
                "stream": stream,
            }
            tools = self._to_openai_tools(req.tools)
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            resp = None
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    resp = requests.post(
                        url, headers=headers, json=payload, timeout=120, stream=stream
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    continue
            if resp is None:
                yield ChatChunk(text=f"[provider-openai] request failed: {last_exc}")
                return
            if resp.status_code != 200:
                yield ChatChunk(text=f"[provider-openai] HTTP {resp.status_code}: {resp.text[:400]}")
                return
            if stream:
                yield from self._consume_stream(resp)
            else:
                yield from self._consume_json(resp)
        except Exception as exc:  # noqa: BLE001
            # malformed stream, missing keys ... report instead of crash
            yield ChatChunk(text=f"[provider-openai] stream error: {exc}")

    def _consume_stream(self, resp):
        """Parse a Server-Sent-Events response, yielding chunks as they arrive."""
        tool_acc: dict[int, dict] = {}
        usage = None
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except Exception:  # noqa: BLE001
                continue
            if event.get("usage"):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                yield ChatChunk(reasoning=delta["reasoning_content"])
            if delta.get("content"):
                yield ChatChunk(text=delta["content"])
            for tc in delta.get("tool_calls") or []:
                idx = int(tc.get("index", 0))
                acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    acc["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    acc["name"] = fn["name"]
                if fn.get("arguments"):
                    acc["arguments"] += fn["arguments"]
        # emit accumulated tool calls in index order
        for idx in sorted(tool_acc):
            acc = tool_acc[idx]
            try:
                args = json.loads(acc["arguments"] or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            wire = acc["name"] or ""
            yield ChatChunk(
                tool_call=ToolCall(
                    id=acc["id"] or "",
                    name=self._name_map.get(wire, wire),
                    arguments=args,
                )
            )
        done_chunk = ChatChunk(done=True)
        if usage and hasattr(done_chunk, "usage"):
            done_chunk.usage = usage
        yield done_chunk

    def _consume_json(self, resp):
        """Non-streaming fallback (stream=false in config)."""
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        if content:
            yield ChatChunk(text=content)
        if reasoning:
            yield ChatChunk(reasoning=reasoning)
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            wire = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            yield ChatChunk(
                tool_call=ToolCall(id=tc.get("id") or "", name=self._name_map.get(wire, wire), arguments=args)
            )
        done_chunk = ChatChunk(done=True)
        usage = data.get("usage")
        if usage and hasattr(done_chunk, "usage"):
            done_chunk.usage = usage
        yield done_chunk


def setup(kernel: KernelApi) -> None:
    kernel.service("provider", OpenAIProvider(kernel))


def teardown(kernel: KernelApi) -> None:
    pass
