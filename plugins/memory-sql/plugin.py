"""memory-sql: SQLite-backed session history + cross-session facts.

Drop-in replacement for memory-jsonl with the SAME service interface
(load / append / save / store_fact / recall_facts / forget_fact / recall_all)
and the same mem.store / mem.recall / mem.forget tools. All data lives in a
single SQLite database (memory/memory.db) instead of JSONL files.

How it becomes the active backend: the kernel registers services and tools
last-wins, and plugins load in sorted directory order — "memory-sql" sorts
after "memory-jsonl", so it takes over the "memory" service and the mem.*
tools automatically. No kernel changes, no config. Remove (or rename) the
jsonl plugin to disable the JSONL backend entirely.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from jarvis.types import ChatMessage, KernelApi


def setup(kernel: KernelApi) -> None:
    db = _SqlMemory(Path(kernel.data_dir) / "memory" / "memory.db")
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


def teardown(kernel: KernelApi) -> None:
    pass


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
                CREATE TABLE IF NOT EXISTS facts (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ts    INTEGER NOT NULL
                );
                """
            )
            self._conn.commit()

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
        prev_key: "tuple[str, str, str | None] | None" = None
        for role, content, name, tool_calls_json, reasoning in rows:
            if role not in ("user", "assistant", "tool", "system"):
                continue  # unknown/malformed role: drop
            # name is part of the key so two DIFFERENT tools returning the
            # same text are never collapsed (tool_call_id pairing relies on
            # every tool result being present).
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

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 03:46:54 ---
