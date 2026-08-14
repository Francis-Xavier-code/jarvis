"""memory-jsonl: per-session conversation history + cross-session facts.

Two stores, both plain JSONL under JARVIS_DATA:
  * sessions/<session>.jsonl  - full conversation history per session
  * memory/facts.jsonl        - cross-session facts (mem.store/recall/forget)

The kernel persists full history (tool_calls + reasoning) so multi-turn tool
rounds replay faithfully. Facts are injected into the context every turn,
so the assistant actually *remembers* what the user told it earlier.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from jarvis.types import ChatMessage, KernelApi

DATA_ROOT = Path(os.environ.get("JARVIS_DATA", "")) or Path(
    __file__
).resolve().parents[2] / "data"


def _path(session: str) -> Path:
    d = DATA_ROOT / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    # guard against path traversal in session id
    safe = "".join(c for c in session if c.isalnum() or c in "-_")
    return d / f"{safe or 'default'}.jsonl"


def _facts_path() -> Path:
    d = DATA_ROOT / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "facts.jsonl"


def setup(kernel: KernelApi) -> None:
    kernel.service("memory", _JsonlMemory())

    @kernel.tool(
        "mem.store",
        "Remember a fact across sessions (overwrites any previous value with the same key)",
        {"key": {"type": "string"}, "value": {"type": "string"}},
    )
    def mem_store(key: str, value: str) -> str:
        if not key.strip():
            return "[mem] key must not be empty"
        _JsonlMemory().store_fact(key, value)
        return f"[mem] stored {key!r}"

    @kernel.tool(
        "mem.recall",
        "Recall stored facts (all of them, or one by key)",
        {"key": {"type": "string"}},
    )
    def mem_recall(key: str = "") -> str:
        facts = _JsonlMemory().recall_facts()
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
        if _JsonlMemory().forget_fact(key):
            return f"[mem] forgot {key!r}"
        return f"[mem] no fact stored under {key!r}"


def teardown(kernel: KernelApi) -> None:
    pass


class _JsonlMemory:
    kind = "memory"

    # ---- session history ----
    @staticmethod
    def _dump(msg: ChatMessage) -> dict:
        d: dict = {"role": msg.role, "content": msg.content, "name": msg.name}
        if msg.tool_calls:
            d["tool_calls"] = msg.tool_calls
        if msg.reasoning_content:
            d["reasoning_content"] = msg.reasoning_content
        return d

    def load(self, session: str) -> list[ChatMessage]:
        p = _path(session)
        if not p.exists():
            return []
        out: list[ChatMessage] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(
                    ChatMessage(
                        role=d["role"],
                        content=d.get("content", ""),
                        name=d.get("name"),
                        tool_calls=d.get("tool_calls"),
                        reasoning_content=d.get("reasoning_content"),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return out

    def append(self, session: str, msg: ChatMessage) -> None:
        p = _path(session)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self._dump(msg), ensure_ascii=False) + "\n")

    def save(self, session: str, messages: list[ChatMessage]) -> None:
        """Full-history overwrite (used by the kernel at the end of a turn)."""
        p = _path(session)
        with p.open("w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(self._dump(msg), ensure_ascii=False) + "\n")

    # ---- cross-session facts ----
    def store_fact(self, key: str, value: str) -> None:
        """Store a fact, replacing any earlier value with the same key."""
        p = _facts_path()
        rows: list[dict] = []
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                    if d.get("key") != key:
                        rows.append(d)
                except Exception:  # noqa: BLE001
                    continue
        rows.append({"key": key, "value": value, "ts": int(time.time())})
        with p.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def recall_facts(self) -> list[dict]:
        """All stored facts, newest last."""
        p = _facts_path()
        if not p.exists():
            return []
        out: list[dict] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                out.append({"key": d["key"], "value": d["value"], "ts": d.get("ts", 0)})
            except Exception:  # noqa: BLE001
                continue
        return out

    def forget_fact(self, key: str) -> bool:
        """Remove a fact. Returns True when something was removed."""
        p = _facts_path()
        if not p.exists():
            return False
        kept: list[dict] = []
        removed = False
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if d.get("key") == key:
                removed = True
            else:
                kept.append(d)
        with p.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return removed

    def recall_all(self) -> str:
        """Compact fact summary for context injection ("" when no facts)."""
        facts = self.recall_facts()
        if not facts:
            return ""
        return "\n".join(f"- {f['key']}: {f['value']}" for f in facts[-20:])
