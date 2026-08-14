# agent-tools

Gives the assistant real **bash + filesystem** tools (pi-agent style), so it
can do work on this machine instead of just talking about it.

- **kind**: `tool`
- **provides**:
  - `bash.execute` — run a shell command (user confirmation required each time)
  - `fs.read` — read a UTF-8 text file
  - `fs.write` / `fs.edit` / `fs.append` — modify files (auto-backup first)
  - `fs.list` / `fs.glob` — discover files
  - `fs.undo` — restore a file from its latest auto-backup

## Security model

* **Every `bash.execute` requires explicit user confirmation** (interactive
  y/N prompt; replaceable via `kernel.confirm_action`).
* **Inside the project root** (including JARVIS plugins): editable directly —
  the kernel hot-reloads edits, and a failed reload **rolls back** to the
  previous registrations, so a broken edit never kills a capability.
* **Outside the project root**: requires user confirmation.
* **Refused outright**: `config.toml` (holds secrets) for read *and* write;
  writes into `.git/`, `.venv/`, `data/`, `sessions/`, `backups/`.

## Rollback safety (self-repair loop)

Every write/edit/append snapshots the previous file into
`<data_dir>/backups/` (last 5 kept). If the assistant edits something into a
broken state:

1. the plugin hot-reload fails, and the **old tools stay loaded** (rollback);
2. ask the assistant to call `fs.undo(path)` (or fix the file);
3. the next hot-reload check loads the repaired file. Done — no restart, no
   lost capabilities.
