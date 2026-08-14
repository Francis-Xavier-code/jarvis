# Changelog

All notable changes to the JARVIS project are recorded here. The project
version lives in pyproject.toml; plugin-level changes live in each
plugins/<name>/CHANGELOG.md (see PLUGIN_SPEC §7.2).

## [Unreleased]

### Added
- **auto-approve**: `auto_approve = true` in config.toml approves
  assistant-initiated actions (bash commands, out-of-root file writes, plugin
  installs) without interactive y/N prompts — for trusted/headless setups;
  read live from the config, so toggling config.toml hot-reloads into effect
- **TUI auto-approve switch**: `/autoapprove [on|off|toggle]` command flips
  the gate live from the TUI and persists it to config.toml (config-core now
  supports writing keys back to the file, comments preserved); startup banner
  shows the current auto-approve state

## [0.2.0] - 2026-08-15 — agent-ready

### Added
- **self-awareness**: plugin-self injects a compact identity/capability
  prompt into every turn; self.whoami / capabilities / version / config tools
- **personality plugin**: configurable persona (name/style/traits/rules)
  injected ahead of the self prompt — layered context: personality -> self ->
  remembered facts -> history
- **memory**: cross-session facts (mem.store / mem.recall / mem.forget)
  persisted to JSONL and injected into every turn; conversation budget
  (memory.max_rounds) trims what is sent while keeping full history
- **cache-core plugin**: transparent LLM response cache (LRU + TTL,
  configurable); errors never cached; cache.stats()
- **agent-tools plugin**: bash.execute (per-command confirmation) and fs.*
  (read/write/edit/append/list/glob/undo) with automatic backups,
  reload-rollback safety, edit signatures with host-isolated identity
  ([agent-identity], never reads ~/.gitconfig), agent.identity and
  plugin.log_change tools
- **web-tools plugin**: web.search (DuckDuckGo, zero API key) + web.fetch
  (readable-text extraction), http(s)-only with timeouts and size caps
- **log-stats plugin**: per-request logging (tokens, cache hit, rounds, tool
  calls) to data/logs/requests.jsonl; `jarvis stats` aggregation
- **terminal REPL**: streaming output, readline history, multi-line input and
  paste detection, hotkeys (Ctrl-C interrupt, Ctrl-D exit, /commands), tool
  completion feedback (✓/✗ + duration), thinking hints
- **channel-tui plugin**: full-screen textual TUI (output/input panels so
  typing never interleaves with streaming), inline y/N confirmations in the
  input row, animated spinner while tools run; `jarvis tui` command
- **plugin CHANGELOG standard** (PLUGIN_SPEC §7.2): every plugin ships
  CHANGELOG.md; every change must add an entry and bump plugin.toml version;
  enforced by plugin.log_change and `jarvis doctor` checks
- **security**: secret redaction in assistant output (configured keys +
  credential shapes); http(s)-only assistant installs with explicit
  confirmation; clone directory-name whitelist
- **CLI**: `jarvis doctor` health check (deps, data dir, plugins, API key,
  changelog compliance); `jarvis stats`; `jarvis tui`

### Changed
- plugin loader treats each plugin dir as a package: submodule imports work
  and hot-reload purges stale submodules; failed reloads roll back to the
  previous registrations
- agent loop: per-round tool-table snapshot used for both dispatch and the
  provider request; provider failures degrade to error text; tool_call_id
  threaded from the provider for faithful replay
- provider-openai: precise tool_call_id pairing (history order), dot-free
  wire names replayed consistently, reasoning_content echoed only when
  non-empty, token usage attached defensively (older kernels tolerated)
- memory-jsonl: full-history persistence incl. tool_calls/reasoning; role
  whitelist and consecutive-duplicate dedup on load
- kernel API: formal confirm() gate and snapshot() view for plugins

### Fixed
- homeassistant config wiring (ha_base_url/ha_token now reach the API calls)
- plugin install path traversal (clone name whitelist)
- bootstrap no longer claims a watcher it cannot keep
- context trimming keeps the current turn intact (tool results never split
  from their assistant call)
- ChatChunk.usage hot-reload mismatch (defensive construction)

## [0.1.0] - 2026-08-14 — microkernel foundation

### Added
- microkernel architecture: everything is a plugin (provider / memory /
  channel / config / tool), with per-turn tool-table snapshots
- plugin manager: discovery from plugins/*/plugin.toml, manifest validation,
  hot-reload via content-hash fingerprint, git puller (install / uninstall,
  bootstrap from plugin-sources.toml)
- provider-openai: OpenAI-compatible chat completions (opencodego aggregator
  default), deepseek reasoning_content support, tool calling
- memory-jsonl: per-session JSONL history; config-core: config-as-plugin;
  channel-terminal: REPL; plugin-self: initial self-awareness
- plugin spec v1.0 (frozen decisions: str-only tools, sync provider, no
  auto-deps, free-form config) with bilingual docs and per-plugin READMEs
- CI (uv + pytest) and .hermes/.jarvis-cloned gitignores
