# Changelog — memory-sql

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.3] - 2026-08-15

### Fixed
- load() never dedupes structural rows (tool results, assistant tool_calls): the old (role, content, name) key collapsed consecutive empty-content assistant tool rounds and identical tool results, orphaning tool_call_id pairs and 400-ing the upstream on replay (by JARVIS <jarvis@jarvis.local>)

## [0.1.2] - 2026-08-15

### Added
- mem.status / mem.migrate tools (backend + counts + migration stats; on-demand re-scan) (by JARVIS <jarvis@jarvis.local>)
- merge migration: sessions already in SQL get their missing older JSONL rows merged in front (chronological order, exact-row dedupe) (by JARVIS <jarvis@jarvis.local>)

### Changed
- migration now scans data_dir, $JARVIS_DATA and cwd (older memory-jsonl wrote there); idempotent per row, re-runs only add new data (by JARVIS <jarvis@jarvis.local>)
- teardown closes the SQLite connection (by JARVIS <jarvis@jarvis.local>)

## [0.1.1] - 2026-08-15

### Changed
- feat: new memory-sql plugin — SQLite backend for session history + facts (same interface as memory-jsonl; last-wins service/tool registration takes over automatically; WAL, thread-safe, single memory/memory.db) (by JARVIS <jarvis@jarvis.local>)
