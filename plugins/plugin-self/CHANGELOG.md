# Changelog — plugin-self

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- self-awareness system prompt injected every turn (compact tool names)
- self.whoami / self.capabilities / self.version / self.config
- memory-aware capabilities (mem.* hints)
- nudge: use fs.* tools for traceable edits

