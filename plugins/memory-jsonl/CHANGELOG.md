# Changelog — memory-jsonl

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- per-session JSONL conversation history (load/append/save)
- full-history persistence incl. tool_calls and reasoning_content
- cross-session facts: mem.store / mem.recall / mem.forget
- facts injected into every turn context (recall_all)
- role whitelist + consecutive-duplicate dedup on load

