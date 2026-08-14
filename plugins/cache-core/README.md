# cache-core

Transparent **response cache** for LLM calls - the token saver. The kernel
asks this plugin before every provider call; on a cache hit the stored
chunks are replayed and the provider (and its tokens) are skipped entirely.

- **kind**: `tool` (registers a `cache` service)
- **provides**: no tools; a `cache` service with `get/put/stats/clear`

## How it saves tokens

* **Exact-request caching** - the fingerprint covers model + full message
  list + tool table, so identical requests never hit the LLM twice.
* **Prefix stability** - with plugin-self injected, the system prompt is
  byte-identical unless the plugin/tool set changes, so upstream
  context-caching (e.g. DeepSeek prompt cache) keeps hitting the same prefix.
* **Errors are never cached** - only responses ending in `done=True` are
  stored, so fixing your API key takes effect immediately.

## Config (config.toml)

```toml
[cache]
enabled = true      # set false to bypass
ttl_seconds = 300   # entry lifetime in seconds
max_entries = 64    # LRU cap
```

## Stats

`cache.stats()` reports hits/misses/hit_rate/entries - wire it into a tool or
log it to see how much you are saving.
