# Changelog — provider-openai

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.2.2] - 2026-08-15

### Fixed
- detect streams that end without [DONE] (upstream cut): the reply is flagged as possibly truncated and yields no done chunk, so the kernel cache never stores a partial response (by JARVIS <jarvis@jarvis.local>)

## [0.2.1] - 2026-08-15

### Changed
- fix: pin resp.encoding=utf-8 — upstream may omit charset, requests then assumes latin-1 and garbles UTF-8 Chinese text in SSE/json (by JARVIS <jarvis@jarvis.local>)

## [0.2.0] - 2026-08-15

### Added
- true SSE streaming (stream=true): first token arrives as produced, tool-call arguments accumulated per index, usage parsed; non-streaming fallback behind stream=false (by JARVIS <jarvis@jarvis.local>)

## [0.1.0] - 2026-08-15

### Added
- OpenAI-compatible chat completions provider (opencodego default)
- tool calling with precise tool_call_id pairing (history order)
- dot-free wire names for tool functions, consistent replay
- token usage attached to the done chunk (defensive vs old kernels)
- reasoning_content echo only when non-empty

