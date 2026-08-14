"""cache-core: transparent response cache for LLM calls (saves tokens).

Wraps the provider: the kernel asks the cache for a request fingerprint
before calling the provider; on a hit the cached chunks are replayed and the
provider call (and its tokens) are skipped entirely.

The fingerprint covers model + full message list + tool table, so only
*identical* requests hit - e.g. "user asks the same thing again in a fresh
session" or replaying the same prefix. Combined with a stable system prompt
(plugin-self), repeated work amortises to a single upstream call.

Only complete, successful provider responses are cached (a trailing
ChatChunk(done=True) marks success); error stubs are never stored, so a fixed
config/API key is picked up immediately.

Config (optional, via config-core [cache] section):
  enabled      = true    # set false to bypass entirely
  ttl_seconds  = 300     # how long an entry lives
  max_entries  = 64      # LRU cap
"""
from __future__ import annotations

import copy
import json
import time
from collections import OrderedDict

from jarvis.types import ChatChunk, ChatRequest, KernelApi

DEFAULTS = {"enabled": True, "ttl_seconds": 300, "max_entries": 64}


def _req_key(req: ChatRequest) -> tuple:
    """Stable hashable fingerprint of a request (model + messages + tools).

    Every field that affects the provider output is included, so a cache hit
    implies the exact same upstream call would be made.
    """
    msgs = tuple(
        (
            m.role,
            m.content,
            m.name,
            json.dumps(m.tool_calls, ensure_ascii=False, sort_keys=True, default=str) if m.tool_calls else None,
            m.reasoning_content,
        )
        for m in req.messages
    )
    tools = tuple(
        (
            t.name,
            t.description,
            json.dumps(t.parameters or {}, ensure_ascii=False, sort_keys=True, default=str),
        )
        for t in req.tools
    )
    return (req.model, tools, msgs)


class _CacheService:
    kind = "cache"

    def __init__(
        self,
        kernel: KernelApi,
        enabled: bool = True,
        ttl_seconds: int = 300,
        max_entries: int = 64,
    ) -> None:
        self._kernel = kernel
        self.enabled = enabled
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._entries: "OrderedDict[tuple, tuple[float, list[ChatChunk]]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, req: ChatRequest) -> "list[ChatChunk] | None":
        """Return cached chunks for this request, or None on a miss."""
        if not self.enabled:
            self.misses += 1
            return None
        key = _req_key(req)
        item = self._entries.get(key)
        if item is None:
            self.misses += 1
            return None
        expires_at, chunks = item
        if expires_at < time.time():
            del self._entries[key]
            self.misses += 1
            return None
        self._entries.move_to_end(key)  # LRU refresh
        self.hits += 1
        return [copy.deepcopy(c) for c in chunks]

    def put(self, req: ChatRequest, chunks: "list[ChatChunk]") -> None:
        """Store chunks for this request (only complete, successful responses).

        A response is considered complete when its last chunk carries
        done=True - provider error paths (missing key, HTTP error, invalid
        body) never emit that, so they are never cached.
        """
        if not self.enabled or not chunks:
            return
        if not chunks[-1].done:
            return
        key = _req_key(req)
        self._entries[key] = (time.time() + self.ttl, chunks)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)  # evict LRU

    def clear(self) -> None:
        self._entries.clear()

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "enabled": self.enabled,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "entries": len(self._entries),
            "ttl_seconds": self.ttl,
            "max_entries": self.max_entries,
        }


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def setup(kernel: KernelApi) -> None:
    cfg = kernel.config.get("cache", {}) or {}
    kernel.service(
        "cache",
        _CacheService(
            kernel,
            enabled=_as_bool(cfg.get("enabled", DEFAULTS["enabled"])),
            ttl_seconds=int(cfg.get("ttl_seconds", DEFAULTS["ttl_seconds"])),
            max_entries=int(cfg.get("max_entries", DEFAULTS["max_entries"])),
        ),
    )


def teardown(kernel: KernelApi) -> None:
    pass
