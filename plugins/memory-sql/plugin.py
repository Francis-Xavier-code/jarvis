"""memory-sql: SQLite-backed session history + cross-session facts.

Drop-in replacement for memory-jsonl with the SAME service interface
(load / append / save / store_fact / recall_facts / forget_fact / recall_all)
and the same mem.store / mem.recall / mem.forget tools, plus mem.status and
mem.migrate. All data lives in a single SQLite database
(<data_dir>/memory/memory.db) instead of JSONL files.

Backend takeover: the kernel registers services and tools last-wins, and
plugins load in sorted directory order — "memory-sql" sorts after
"memory-jsonl", so it takes over the "memory" service and the mem.* tools
automatically. No kernel changes, no config. Remove (or rename) the jsonl
plugin to disable the JSONL backend entirely.

Legacy migration: memory-jsonl data (sessions/*.jsonl and memory/facts.jsonl)
is imported into SQLite on startup and on demand via mem.migrate. Candidate
roots are scanned in order:
  1. <data_dir>             (where the DB itself lives)
  2. $JARVIS_DATA           (when set and different)
  3. the current working directory (older memory-jsonl versions wrote there)
The import is idempotent per session/fact, so re-runs only pick up new data
and never duplicate existing rows.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from jarvis.types import ChatMessage, KernelApi

_ACTIVE: "_SqlMemory | None" = None


def setup(kernel: KernelApi) -> None:
    global _ACTIVE
    db = _SqlMemory(Path(kernel.data_dir) / "memory" / "memory.db")
    _ACTIVE = db
    kernel.service("memory", db)

    @kernel.tool(
        "mem.store",
        "Remember a fact across sessions (overwrites any previous value with the same key)",
        {"key": {"type": "string"}, "value": {"type": "string"}},
    )
    def mem_store(key: str, value: str) -> str:
        if not key.strip():
            return "[mem] key must not be empty"
        db.store_fact(key, value)
        return f"[mem] stored {key!r}"

    @kernel.tool(
        "mem.recall",
        "Recall stored facts (all of them, or one by key)",
        {"key": {"type": "string"}},
    )
    def mem_recall(key: str = "") -> str:
        facts = db.recall_facts()
        if key:
            matches = [f for f in facts if f["key"] == key]
            if not matches:
                return f"[mem] no fact stored under {key!r}"
            return f"{key}: {matches[-1]['value']}"
        if not facts:
            return "[mem] no facts stored yet"
        return "\n".join(f"{f['key']}: {f['value']}" for f in facts)

    @kernel.tool(
        "mem.forget",
        "Forget a stored fact by key",
        {"key": {"type": "string"}},
    )
    def mem_forget(key: str) -> str:
        if db.forget_fact(key):
            return f"[mem] forgot {key!r}"
        return f"[mem] no fact stored under {key!r}"

    @kernel.tool(
        "mem.status",
        "Show the active memory backend (sql/jsonl), database path, stored counts and legacy-migration stats",
        {"detail": {"type": "boolean"}},
    )
    def mem_status(detail: bool = False) -> str:
        s = db.stats()
        lines = [
            f"backend: sqlite ({s['db_path']})",
            f"messages: {s['messages']} in {s['sessions']} sessions",
            f"facts: {s['facts']}",
        ]
        if detail:
            mig = s.get("migrated") or {}
            if mig.get("sessions") or mig.get("merged_messages") or mig.get("facts"):
                lines.append(
                    f"migrated from JSONL: {mig['sessions']} sessions / "
                    f"{mig['messages']} messages new, "
                    f"{mig['merged_messages']} messages merged into {mig['merged_sessions']} existing sessions, "
                    f"{mig['facts']} facts "
                    f"(roots: {', '.join(mig.get('roots', []))})"
                )
            else:
                lines.append("migrated from JSONL: nothing found (or already migrated)")
        return "\n".join(lines)

    @kernel.tool(
        "mem.migrate",
        "Re-scan legacy memory-jsonl locations and import any new sessions/facts into SQLite (idempotent)",
    )
    def mem_migrate() -> str:
        s = db.migrate()
        return (
            f"[mem] migration: {s['sessions']} new sessions / {s['messages']} messages, "
            f"{s['merged_sessions']} existing sessions merged with {s['merged_messages']} older messages, "
            f"{s['facts']} facts (roots: {', '.join(s['roots'])})"
        )


def teardown(kernel: KernelApi) -> None:
    global _ACTIVE
    if _ACTIVE is not None:
        try:
            _ACTIVE.close()
        except Exception:  # noqa: BLE001
            pass
        _ACTIVE = None


class _SqlMemory:
    kind = "memory"

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    session    TEXT    NOT NULL,
                    seq        INTEGER NOT NULL,
                    role       TEXT    NOT NULL,
                    content    TEXT    NOT NULL DEFAULT '',
                    name       TEXT,
                    tool_calls TEXT,
                    reasoning  TEXT,
                    PRIMARY KEY (session, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session);
                CREATE TABLE IF NOT EXISTS facts (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ts    INTEGER NOT NULL
                );
                """
            )
            self._conn.commit()
        self._migrated: dict = {}
        self.migrate()

    # ---- legacy JSONL migration ----
    def _candidate_roots(self) -> list[Path]:
        """data_dir, $JARVIS_DATA, then cwd — deduped, existing dirs only."""
        roots: list[Path] = []
        for raw in (self._path.parents[1], os.environ.get("JARVIS_DATA"), os.getcwd()):
            if not raw:
                continue
            p = Path(raw)
            if p not in roots and p.is_dir():
                roots.append(p)
        return roots

    def _session_exists(self, session: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE session = ? LIMIT 1", (session,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _read_jsonl_rows(p: Path) -> "list[tuple]":
        """Parse a JSONL session file into (role, content, name, tool_calls_json,
        reasoning) tuples. Malformed lines and unknown roles are skipped, like
        memory-jsonl."""
        rows: "list[tuple]" = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(d, dict):
                continue  # a JSON scalar line (e.g. a quoted string) is not a message
            role = d.get("role")
            if role not in ("user", "assistant", "tool", "system"):
                continue
            rows.append(
                (
                    role,
                    d.get("content", "") or "",
                    d.get("name"),
                    json.dumps(d.get("tool_calls"), ensure_ascii=False) if d.get("tool_calls") else None,
                    d.get("reasoning_content") or None,
                )
            )
        return rows

    @staticmethod
    def _row_key(role, content, name, tc_json, reasoning) -> tuple:
        """Normalised identity of a message row (used for exact dedupe)."""
        if tc_json is not None:
            try:
                tc_json = json.dumps(json.loads(tc_json), ensure_ascii=False, sort_keys=True)
            except Exception:  # noqa: BLE001
                pass
        return (role, content, name, tc_json, reasoning)

    def _insert_rows(self, session: str, rows: "list[tuple]", start_seq: int = 0) -> int:
        for i, (role, content, name, tc_json, reasoning) in enumerate(rows):
            self._conn.execute(
                "INSERT INTO messages (session, seq, role, content, name, tool_calls, reasoning) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session, start_seq + i, role, content, name, tc_json, reasoning),
            )
        return len(rows)

    def _import_session_file(self, p: Path, session: str) -> int:
        """Import one JSONL session file; returns the number of rows inserted."""
        rows = self._read_jsonl_rows(p)
        return self._insert_rows(session, rows) if rows else 0

    def _merge_session_file(self, p: Path, session: str) -> int:
        """A session already exists in SQL but its JSONL file holds OLDER rows
        (the JSONL froze when the backend switched). Merge the missing JSONL
        rows IN FRONT of the SQL rows so the conversation stays chronological;
        rows already present are skipped (exact content match)."""
        jsonl_rows = self._read_jsonl_rows(p)
        if not jsonl_rows:
            return 0
        sql_rows = self._conn.execute(
            "SELECT role, content, name, tool_calls, reasoning FROM messages "
            "WHERE session = ? ORDER BY seq",
            (session,),
        ).fetchall()
        seen = {
            self._row_key(r, c, n, tc, rc)
            for r, c, n, tc, rc in sql_rows
        }
        missing = []
        for row in jsonl_rows:
            key = self._row_key(*row)
            if key in seen:
                continue
            seen.add(key)
            missing.append(row)
        if not missing:
            return 0
        # rebuild: JSONL rows (older) first, then the existing SQL rows
        self._conn.execute("DELETE FROM messages WHERE session = ?", (session,))
        seq = self._insert_rows(session, missing)
        seq += self._insert_rows(
            session,
            [(r, c, n, tc, rc) for r, c, n, tc, rc in sql_rows],
            start_seq=seq,
        )
        return len(missing)

    def _import_facts_file(self, p: Path) -> int:
        inserted = 0
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(d, dict):
                continue
            key, value = d.get("key"), d.get("value")
            if not key:
                continue
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO facts (key, value, ts) VALUES (?, ?, ?)",
                (key, value, d.get("ts", 0)),
            )
            inserted += cur.rowcount
        return inserted

    def migrate(self) -> dict:
        """Import legacy memory-jsonl data not already in the DB. Idempotent:
        sessions already present and facts already stored are skipped, so
        re-running only picks up new data."""
        roots = self._candidate_roots()
        stats = {
            "roots": [str(r) for r in roots],
            "sessions": 0,
            "messages": 0,
            "merged_sessions": 0,
            "merged_messages": 0,
            "facts": 0,
        }
        with self._lock:
            for root in roots:
                sessions_dir = root / "sessions"
                if sessions_dir.is_dir():
                    for p in sorted(sessions_dir.glob("*.jsonl")):
                        session = p.stem
                        if self._session_exists(session):
                            n = self._merge_session_file(p, session)
                            if n:
                                stats["merged_sessions"] += 1
                                stats["merged_messages"] += n
                            continue
                        n = self._import_session_file(p, session)
                        if n:
                            stats["sessions"] += 1
                            stats["messages"] += n
                facts_file = root / "memory" / "facts.jsonl"
                if facts_file.is_file():
                    stats["facts"] += self._import_facts_file(facts_file)
            self._conn.commit()
        self._migrated = stats
        return stats

    # ---- session history ----
    @staticmethod
    def _dump(msg: ChatMessage) -> tuple:
        return (
            msg.role,
            msg.content or "",
            msg.name,
            json.dumps(msg.tool_calls, ensure_ascii=False) if msg.tool_calls else None,
            msg.reasoning_content or None,
        )

    def load(self, session: str) -> list[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, name, tool_calls, reasoning FROM messages "
                "WHERE session = ? ORDER BY seq",
                (session,),
            ).fetchall()
        out: list[ChatMessage] = []
        prev_key: "tuple | None" = None
        for role, content, name, tool_calls_json, reasoning in rows:
            if role not in ("user", "assistant", "tool", "system"):
                continue  # unknown/malformed role: drop
            if role == "tool" or tool_calls_json:
                # Structural rows: tool results and assistant
                # tool_calls are pairing-critical (tool_call_id
                # replay) - NEVER dedupe them, even when identical
                # (two different calls may return the same text).
                out.append(
                    ChatMessage(
                        role=role,
                        content=content,
                        name=name,
                        tool_calls=json.loads(tool_calls_json) if tool_calls_json else None,
                        reasoning_content=reasoning or None,
                    )
                )
                continue
            # Dedupe only plain text rows: consecutive identical
            # input (double-submitted) would otherwise replay twice.
            key = (role, content, name)
            if key == prev_key:
                continue  # consecutive duplicate (double-submitted input)
            prev_key = key
            out.append(
                ChatMessage(
                    role=role,
                    content=content,
                    name=name,
                    tool_calls=json.loads(tool_calls_json) if tool_calls_json else None,
                    reasoning_content=reasoning or None,
                )
            )
        return out

    def append(self, session: str, msg: ChatMessage) -> None:
        with self._lock:
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE session = ?",
                (session,),
            ).fetchone()[0]
            self._conn.execute(
                "INSERT INTO messages (session, seq, role, content, name, tool_calls, reasoning) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session, seq, *self._dump(msg)),
            )
            self._conn.commit()

    def save(self, session: str, messages: list[ChatMessage]) -> None:
        """Full-history overwrite (used by the kernel at the end of a turn)."""
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session = ?", (session,))
            self._conn.executemany(
                "INSERT INTO messages (session, seq, role, content, name, tool_calls, reasoning) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(session, i, *self._dump(m)) for i, m in enumerate(messages)],
            )
            self._conn.commit()

    # ---- cross-session facts ----
    def store_fact(self, key: str, value: str) -> None:
        """Store a fact, replacing any earlier value with the same key."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, ts = excluded.ts",
                (key, value, int(time.time())),
            )
            self._conn.commit()

    def recall_facts(self) -> list[dict]:
        """All stored facts, newest last."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, ts FROM facts ORDER BY ts, key"
            ).fetchall()
        return [{"key": k, "value": v, "ts": t} for k, v, t in rows]

    def forget_fact(self, key: str) -> bool:
        """Remove a fact. Returns True when something was removed."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            self._conn.commit()
        return cur.rowcount > 0

    def recall_all(self) -> str:
        """Compact fact summary for context injection ("" when no facts)."""
        facts = self.recall_facts()
        if not facts:
            return ""
        return "\n".join(f"- {f['key']}: {f['value']}" for f in facts[-20:])

    def stats(self) -> dict:
        with self._lock:
            msgs = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            sess = self._conn.execute("SELECT COUNT(DISTINCT session) FROM messages").fetchone()[0]
            facts = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        return {
            "db_path": str(self._path),
            "messages": msgs,
            "sessions": sess,
            "facts": facts,
            "migrated": self._migrated,
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 04:03:00 ---
