# Changelog — provider-openai

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- OpenAI-compatible chat completions provider (opencodego default)
- tool calling with precise tool_call_id pairing (history order)
- dot-free wire names for tool functions, consistent replay
- token usage attached to the done chunk (defensive vs old kernels)
- reasoning_content echo only when non-empty

