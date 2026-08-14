# Changelog — cache-core

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- transparent LLM response cache (LRU + TTL, configurable)
- request fingerprint = model + messages + tools
- errors never cached (only done=True responses)
- cache.stats() hits/misses/hit_rate

