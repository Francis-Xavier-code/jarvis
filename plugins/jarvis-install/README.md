# jarvis-install

The kernel's pull capability, exposed **as a plugin** — because "installing a
plugin" is itself a capability, it lives in the plugin system like everything
else.

- **kind**: `tool`
- **provides** two tools:

```
jarvis.install_plugin(git_url: str, name: str = "") -> str
    Clone a git repo that follows the JARVIS plugin.toml convention into
    plugins/<name>/ and hot-load it. Returns the plugin name.
    Example: a jarvis-homeassistant repo becomes hass.* tools immediately.

jarvis.uninstall_plugin(name: str) -> str
    Tear down and remove a loaded plugin by name.
```

## Equivalent entry points

| Want to… | Use |
|----------|-----|
| install from a conversation | `jarvis.install_plugin` tool |
| install on the command line | `jarvis install <git_url>` |
| install a default-pack at boot | list it in `plugin-sources.toml`, then `jarvis bootstrap` |

All three call the same `Kernel.install_plugin` path.

## Security

This tool clones and executes arbitrary git repositories. **Only install sources
you trust** — a malicious plugin runs with the same privileges as JARVIS.
