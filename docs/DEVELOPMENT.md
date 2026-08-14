# Fixing JARVIS without chain reactions

Every bug fix in this repo is a small self-modification. The discipline below
keeps a fix from chaining into the next bug (the #1 failure mode seen in the
field: unverified fixes piling up on each other).

## The golden loop

```bash
jarvis check                 # 1. baseline: everything green BEFORE you start
# ... make your fix ...
jarvis check                 # 2. everything green AFTER the fix
jarvis snapshot "fixed X"    # 3. checkpoint it - a later bad fix is one --undo away
```

- **Never** consider a fix done until `jarvis check` passes.
- **Never** start a fix on a dirty tree: snapshot first, or you cannot roll back.
- If `jarvis check` fails after your change, `jarvis snapshot --undo` reverts
  the last checkpoint instantly - no archaeology.

## jarvis check

One command: compiles every .py, parses every plugin.toml, runs the full test
suite and `jarvis doctor`. Exits non-zero on any failure. It is the shortest
path from "I changed something" to "I broke nothing".

## jarvis snapshot

```bash
jarvis snapshot "memory dedupe fix"   # git add -A + commit
jarvis snapshot --undo                # git reset --hard HEAD~1 (revert last checkpoint)
```

Checkpoints make git the health log: every verified state is one command away.

## Single-writer rule

Concurrent edits (a running TUI + a human + an agent) are the most common
cause of chain reactions. To lock the tree while you work:

```bash
touch .jarvis-maintenance "I am refactoring memory - don't write"  # or:
echo "why" > .jarvis-maintenance
# now every fs.write/edit/append returns "maintenance mode - refusing writes"
# ... do your work ...
rm .jarvis-maintenance
```

While the lock is present the agent-tools fs.* tools refuse ALL writes, so a
running JARVIS cannot clobber you mid-fix.

## Layered guardrails (already in place)

1. Syntax pre-validation: fs.* refuses .py/.toml content that cannot parse.
2. Atomic writes: hot-reload never sees a half-written file.
3. Frozen paths (.jarvis-frozen): kernel/ + the plugin spec need an explicit
   human yes - auto_approve cannot bypass it.
4. Hot-reload: compile pre-check + stability window + rollback on failure.
5. Auto-backups: every fs write snapshots the previous state (fs.undo restores).
