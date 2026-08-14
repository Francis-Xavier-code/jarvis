"""memory-jsonl: per-session conversation history in plain JSONL.

One file per session under JARVIS_DATA/sessions/<session>.jsonl. Minimal, no
extra dependencies, hot-reload safe (stateless between calls).
"""
from __future__ import annotations

import json
import os
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


def setup(kernel: KernelApi) -> None:
    kernel.service("memory", _JsonlMemory())


def teardown(kernel: KernelApi) -> None:
    pass


class _JsonlMemory:
    kind = "memory"

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
                out.append(ChatMessage(role=d["role"], content=d["content"], name=d.get("name")))
            except Exception:  # noqa: BLE001
                continue
        return out

    def append(self, session: str, msg: ChatMessage) -> None:
        p = _path(session)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"role": msg.role, "content": msg.content, "name": msg.name}) + "\n")
