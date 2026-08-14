# plugin-self

JARVIS's **self-awareness**. It exposes tools the LLM (and you) can call to find
out what JARVIS *is* and what it can currently do. This is the "who am I" surface
— it reads the **live** kernel state (loaded plugins, registered tools), so the
answer is always current, even right after a hot-reload or a freshly installed
plugin.

- **kind**: `tool`
- **provides**:
  - `self.whoami` — short identity blurb (name, architecture, active provider/model)
  - `self.capabilities` — list currently-loaded plugins and every routed tool
  - `self.version` — kernel + plugin-spec versions

Because it inspects the kernel directly, an agent turn that calls `self.capabilities`
after `jarvis.install_plugin` will see the newly added tool — the loop is alive.

## Example

```
you> 你是谁?
jarvis> [calls self.whoami] I am JARVIS, a microkernel AI assistant where
        everything is a plugin... Currently loaded: 7 plugins, 12 tools...
```
