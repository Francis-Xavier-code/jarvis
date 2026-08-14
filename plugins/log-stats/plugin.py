"""log-stats: request logging + token statistics.

Registers a `logger` service. The kernel calls log_turn(entry) at the end of
every chat turn, appending one JSON line to <data_dir>/logs/requests.jsonl:

    {"ts": ..., "session": ..., "model": ..., "prompt_tokens": ...,
     "completion_tokens": ..., "cache_hit": false, "rounds": 1, "tool_calls": 0}

`jarvis stats` (CLI) aggregates these rows into a cost report. No extra
dependencies; safe to hot-reload (stateless between calls).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from jarvis.types import KernelApi


def _logs_path(data_dir: str) -> Path:
    d = Path(data_dir) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "requests.jsonl"


def setup(kernel: KernelApi) -> None:
    kernel.service("logger", _LogService(kernel.data_dir))


def teardown(kernel: KernelApi) -> None:
    pass


class _LogService:
    kind = "logger"

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir

    def log_turn(self, entry: dict) -> None:
        p = _logs_path(self.data_dir)
        try:
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def read_rows(self) -> list[dict]:
        p = _logs_path(self.data_dir)
        if not p.exists():
            return []
        rows = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return rows

    def stats(self) -> dict:
        """Aggregate the log into a small report."""
        rows = self.read_rows()
        if not rows:
            return {"requests": 0}
        pt = sum(r.get("prompt_tokens") or 0 for r in rows)
        ct = sum(r.get("completion_tokens") or 0 for r in rows)
        hits = sum(1 for r in rows if r.get("cache_hit"))
        by_model: dict[str, int] = {}
        for r in rows:
            by_model[r.get("model") or "?"] = by_model.get(r.get("model") or "?", 0) + (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0)
        return {
            "requests": len(rows),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            "cache_hits": hits,
            "cache_hit_rate": round(hits / len(rows), 3) if rows else 0.0,
            "by_model": by_model,
        }
