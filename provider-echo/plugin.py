"""provider-echo: a STUB provider (NOT a real LLM).

It exists only to prove the full chain — user text -> agent loop -> tool
routing -> memory -> output — without depending on a real model or any
base_url/api_key. Real providers (provider-openai, etc.) are added later as
their own plugin directories; the architecture does not change.

Behaviour:
  * if history already contains a tool result -> produce a final answer that
    references it (mimics how a real LLM would finish after a tool call)
  * if the latest user message mentions 'tool' -> emit one tool_call to the
    demo tool ``demo.ping`` (registered by this plugin) to exercise routing
  * otherwise -> echo the last user message
"""
from __future__ import annotations

from jarvis.types import ChatChunk, ChatRequest, KernelApi, ToolCall


def setup(kernel: KernelApi) -> None:
    kernel.service("provider", _EchoProvider())
    # a demo tool so the tool-call path is exercised end-to-end
    @kernel.tool("demo.ping", "Echo a ping with optional note", {"note": {"type": "string"}})
    def ping(note: str = "") -> str:
        return f"pong{note and ': ' + note}"


def teardown(kernel: KernelApi) -> None:
    pass


class _EchoProvider:
    kind = "provider"

    def chat(self, req: ChatRequest):
        last_user = ""
        for m in reversed(req.messages):
            if m.role == "user":
                last_user = m.content
                break
        # a tool result is already in history -> give the final answer
        for m in req.messages:
            if m.role == "tool":
                yield ChatChunk(text=f"[echo] got tool result: {m.content}")
                return
        if "tool" in last_user.lower():
            yield ChatChunk(text="(calling demo tool) ")
            yield ChatChunk(
                tool_call=ToolCall(name="demo.ping", arguments={"note": "from echo"})
            )
            return
        yield ChatChunk(text=f"[echo] {last_user}")
