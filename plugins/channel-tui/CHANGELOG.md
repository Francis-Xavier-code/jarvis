# Changelog — channel-tui

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.6.2] - 2026-08-15

### Fixed
- fix: restore render_whale import (dropped when JARVIS slimmed the ui imports in the auto-approve batch) - NameError on startup (by JARVIS <jarvis@jarvis.local>)

## [0.6.1] - 2026-08-15

### Fixed
- fix: wrap splash dismiss so set_timer does not await it (ScreenError on startup) (by JARVIS <jarvis@jarvis.local>)

## [0.6.0] - 2026-08-15

### Added
- 1:1 dsh-TUI visual port: pixel-whale splash + header (13 frames, RGB half-blocks), big-font JARVIS title with blue-white shimmer, design system (divider/progress/status-icon/byline) (by JARVIS <jarvis@jarvis.local>)

## [0.5.0] - 2026-08-15

### Added
- structured message list (dsh-TUI style): user bubbles, streaming assistant message, collapsible thinking block (ctrl+o), animated tool messages with display names - replaces flat log output (by JARVIS <jarvis@jarvis.local>)

## [0.4.3] - 2026-08-15

### Changed
- replace non-ASCII glyphs (braille spinner, check/cross, gear, arrows) with ASCII-safe symbols so no mojibake on terminals with limited fonts (by JARVIS <jarvis@jarvis.local>)

## [0.4.2] - 2026-08-15

### Fixed
- fix: register jarvis-dark theme explicitly (Textual 8 register_theme) so jarvis tui starts without InvalidThemeError (by JARVIS <jarvis@jarvis.local>)

## [0.4.1] - 2026-08-15

### Changed
- modern UI: jarvis-dark theme (GitHub-dark palette + purple accent), borderless panels, underline input, refined message markers, themed markdown (by JARVIS <jarvis@jarvis.local>)

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
