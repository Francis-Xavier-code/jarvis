# memory-sql

SQLite-backed memory backend for JARVIS: per-session conversation history plus
cross-session facts, stored in one database file
(`<data_dir>/memory/memory.db`) instead of JSONL files.

## What it is

A `kind="memory"` plugin, a drop-in replacement for `memory-jsonl` with the
SAME service interface and the same `mem.store` / `mem.recall` /
`mem.forget` tools, plus two extras:

- `mem.status` — active backend, database path, stored counts, migration stats
- `mem.migrate` — re-scan legacy JSONL locations and import anything new

**Backend takeover**: services and tools register last-wins and plugins load
in sorted directory order — `memory-sql` sorts after `memory-jsonl`, so it
becomes the active memory backend automatically. Remove (or rename) the jsonl
plugin to disable the JSONL backend entirely.

## Legacy JSONL migration

On startup (and on demand via `mem.migrate`) any memory-jsonl data found in
the candidate roots is imported into SQLite, in order:

1. `<data_dir>` — where the DB itself lives
2. `$JARVIS_DATA` — when set and different
3. the current working directory — older memory-jsonl versions wrote there

The import is **idempotent per row**: new sessions are imported fully; sessions
that already exist in SQL get their missing older JSONL rows merged **in
front** (so conversation order stays chronological); facts are inserted only
when absent. Re-running only ever picks up new data — never duplicates.

## Configuration

None required. The database path follows `kernel.data_dir` (default:
`~/Library/Application Support/jarvis/memory/memory.db`).

## Dependencies

None (stdlib `sqlite3` only). WAL mode + a threading lock make it safe with
the kernel's worker thread and hot-reload.

## Install

```bash
jarvis install https://github.com/<you>/memory-sql.git
# or: drop this folder into plugins/ and run jarvis bootstrap
# (it must sort AFTER memory-jsonl to take over — "memory-sql" does)
```

## Security notes

- SQL statements are fully parameterized (session names are data, not SQL).
- Session names are stored verbatim (no path-traversal risk — no file paths
  are derived from them).
- The old JSONL files are **not deleted** after migration — nothing is lost.

<!-- --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 04:03:00 --- -->
