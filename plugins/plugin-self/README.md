# plugin-self

JARVIS's **self-awareness**. Two surfaces:

1. **System-prompt service** (`kind = "self"`) — the kernel injects a freshly
   generated identity + capability summary (loaded plugins, active
   provider/model, every callable tool with its description) at the front of
   **every** provider request. JARVIS *knows* who it is and what it can do
   without having to remember to query — hot-reloads and freshly installed
   plugins show up on the very next turn. The prompt is rebuilt per round and
   never persisted.
2. **`self.*` tools** — on-demand detail for the LLM (and you):

- **kind**: `tool` (plus a `self` service)
- **provides**:
  - `self.whoami` — short identity blurb (name, architecture, provider/model, counts)
  - `self.capabilities` — list every loaded plugin and every routed tool **with its description**
  - `self.version` — kernel + plugin-spec versions
  - `self.config` — which config keys are set (secrets redacted)

Because it inspects the kernel directly, an agent turn that calls `self.capabilities`
after `jarvis.install_plugin` will see the newly added tool — the loop is alive.

## Example

```
you> 你能干什么?
jarvis> [already knows via system prompt; calls self.capabilities for detail]
        JARVIS loaded plugins: ... Callable tools (name: description): ...
```

## Security

`self.config` only ever reports key *names*; values of keys whose name contains
`api_key` / `token` / `secret` / `password` are never surfaced.
