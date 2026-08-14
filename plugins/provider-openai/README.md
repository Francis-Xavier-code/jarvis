# provider-openai

The real **LLM brain** for JARVIS. It speaks the OpenAI Chat Completions API, so
it works against *any* OpenAI-compatible endpoint — which is exactly what a
**model-vendor aggregator** is. The default configured vendor is **opencodego**
(one API key → many underlying vendors: minimax / kimi / glm / deepseek / qwen /
...), but changing the base URL points the same plugin at OpenAI, a local
llama.cpp server, etc.

> English docs: [README.md](README.md)

- **kind**: `provider`
- **provides**: no tools of its own — it is the model

## Configuration

Read from the `config-core` plugin (`config.toml`) **or** environment variables:

| config.toml key | env var | default | meaning |
|-----------------|---------|---------|---------|
| `openai_base_url` | `OPENAI_BASE_URL` | `https://opencode.ai/zen/go/v1` | the API base |
| `openai_api_key` | `OPENAI_API_KEY` | — | the API key (**secret**) |
| `model` | `MODEL` | `kimi-k3` | default model to request |

> **Security**: never commit the API key. Put it in `config.toml` (gitignored —
> see `.gitignore` `config.toml` rule) or, better, export `OPENAI_API_KEY` in your
> shell / a `.env` that is never committed.

## Tool calling

Tool specs from other plugins are forwarded to the model as OpenAI `tools`. When
the model emits a function call, this provider yields a `ChatChunk(tool_call=...)`
and the kernel routes it, feeds the result back, and repeats (up to 4 rounds).
Tool results are re-bound to their `tool_call_id` internally (the kernel does not
track that id for us).

## Dependency

Uses `requests` (soft-imported). Install once:

```
uv pip install requests
```
