# Changelog — memory-jsonl

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.2] - 2026-08-15

### Fixed
- load() never dedupes structural rows (tool results, assistant tool_calls) - same tool_call_id pairing bug as memory-sql (by JARVIS <jarvis@jarvis.local>)

## [0.1.1] - 2026-08-15

### Fixed
- DATA_ROOT fallback: Path("") is truthy, so an unset JARVIS_DATA used to write sessions/ into the cwd instead of the data dir - now falls through to the package default (by JARVIS <jarvis@jarvis.local>)

## [0.1.0] - 2026-08-15

### Added
- per-session JSONL conversation history (load/append/save)
- full-history persistence incl. tool_calls and reasoning_content
- cross-session facts: mem.store / mem.recall / mem.forget
- facts injected into every turn context (recall_all)
- role whitelist + consecutive-duplicate dedup on load

