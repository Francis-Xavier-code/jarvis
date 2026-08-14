"""provider-echo: a STUB provider (NOT a real LLM).

It exists only to prove the full chain — user text -> agent loop -> tool
routing -> memory -> output — without depending on a real model or any
base_url/api_key. Real providers (provider-openai, etc.) are added later as
their own plugin directories; the architecture does not change.

Behaviour:
  * echoes the last user message
  * if the user text contains the word 'tool', it emits a single tool_call to
    the demo tool ``demo.ping`` (registered by this plugin) to exercise the
    tool routing path.
"""
from __future__ import annotations

from jarvis.types import ChatChunk, ChatRequest, KernelApi


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
        # detect a tool-trigger phrase
        if "tool" in last_user.lower():
            yield ChatChunk(text="(calling demo tool) ")
            yield ChatChunk(tool_call=__import__("jarvis.types", fromlist=["ToolCall"]).ToolCall(
                name="demo.ping", arguments={"note": "from echo"}
            ))
            return
        yield ChatChunk(text=f"[echo] {last_user}")
