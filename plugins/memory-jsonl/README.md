# memory-jsonl

Per-session conversation history stored as plain JSONL. Minimal, no extra
dependencies, stateless between calls (safe under hot-reload).

> 中文文档: [README.zh.md](README.zh.md)

- **kind**: `memory`
- **provides**: a memory *service* (not tools)
  - `load(session) -> list[ChatMessage]` — replay a session's history
  - `append(session, msg)` — append one message

## Storage

```
$JARVIS_DATA/sessions/<session>.jsonl
```

`<session>` is sanitised (alphanumerics + `-_` only) to prevent path traversal.
Each line is a JSON object `{"role", "content", "name"}`.

## Notes

- One file per session; history is loaded fresh each turn by the agent loop.
- No tools are exposed — this plugin only backs the kernel's memory service.
- Swap for `memory-sqlite` or any other backend by writing a plugin with
  `kind = "memory"` exposing the same two methods.
