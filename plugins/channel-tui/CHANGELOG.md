# Changelog — channel-tui

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.4.0] - 2026-08-15

### Added
- full turn-lifecycle status: thinking spinner while awaiting the first token, awaiting-confirmation state, explicit 'done (Xs)' completion marker (by JARVIS <jarvis@jarvis.local>)

## [0.3.1] - 2026-08-15

### Changed
- fix y/N confirmations (App-level on_key + submitted fallback; bindings-based history) and polish message display (user/assistant markers, indented tool lines, spacing) (by JARVIS <jarvis@jarvis.local>)

## [0.3.0] - 2026-08-15

### Added
- streamed Markdown rendering in the output panel (inline/block rules, code fences, bracket escaping) - JARVIS-authored, reviewed by dev (by JARVIS <jarvis@jarvis.local>)

## [0.2.0] - 2026-08-15

### Added
- animated spinner while a tool is running (braille frames + tool name in the status row) (by JARVIS <jarvis@jarvis.local>)

## [0.1.1] - 2026-08-15

### Changed
- confirmations moved from modal popup to the input row (y/N on keyboard, no output overlay) (by JARVIS <jarvis@jarvis.local>)

## [0.1.0] - 2026-08-15

### Added
- full-screen textual TUI: output panel + input box + header/footer
- streamed output, inline tool feedback (⚙ / ✓ / ✗ + duration)
- modal confirmation dialogs (y/N) via confirm bridge
- single-line input with history and backslash continuation
- busy queueing for input typed mid-reply
- soft-import of textual (degrades gracefully without it)
