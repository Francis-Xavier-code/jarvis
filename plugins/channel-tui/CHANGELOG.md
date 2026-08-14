# Changelog — channel-tui

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- full-screen textual TUI: output panel + input box + header/footer
- streamed output, inline tool feedback (⚙ / ✓ / ✗ + duration)
- modal confirmation dialogs (y/N) via confirm bridge
- single-line input with history and backslash continuation
- busy queueing for input typed mid-reply
- soft-import of textual (degrades gracefully without it)
