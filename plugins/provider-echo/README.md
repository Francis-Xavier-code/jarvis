# provider-echo  (STUB — NOT a real LLM)

A stand-in provider used to prove the full chain — user text → agent loop →
tool routing → memory → output — **without depending on a real model or any
api key**. Real providers (`provider-openai`, etc.) are added later as their own
plugin directories; the architecture does not change.

> 中文文档: [README.zh.md](README.zh.md)

- **kind**: `provider`
- **provides**: a provider *service* (`_EchoProvider.chat`) **and** one tool

## Tool

```
demo.ping(note: str = "") -> str
    Returns "pong" + optional note. Exists only to exercise tool routing.
```

## Behaviour

1. Echoes the last user message: `[echo] <text>`.
2. If the user message contains the word **"tool"** (and no tool result exists
   yet in history), it emits a `tool_call` to `demo.ping` to exercise the
   tool-routing path.
3. After a tool result is fed back, it produces a final answer referencing that
   result (`[echo] got tool result: ...`).

## Replace me

Do **not** use this in production. Swap it for a real provider plugin
(`kind = "provider"`, implement `.chat(req)` as a sync generator yielding
`ChatChunk`s — see PLUGIN_SPEC §5). The kernel picks the new provider up with no
changes elsewhere.
