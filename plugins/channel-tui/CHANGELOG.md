# Changelog — channel-tui

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.6.10] - 2026-08-15

### Changed
- feat(tui): braille spinner frames, tool-row spinner now animates (was stuck on frame 1) with live elapsed seconds, ✓/✗ completion marks, rounded input with ❯ prefix and focus highlight (by JARVIS <jarvis@jarvis.local>)

## [0.6.9] - 2026-08-15

### Changed
- fix(tui): brand logo widget height auto — 5-row JARVIS logo no longer leaves a ~7-row gap before the chat area (was hardcoded height:13) (by JARVIS <jarvis@jarvis.local>)

## [0.6.8] - 2026-08-15

### Added
- live rendering of the in-flight (unterminated) streamed line - text is visible the moment a chunk arrives, not only after a newline (by JARVIS <jarvis@jarvis.local>)

### Changed
- feat(tui): main-view JARVIS logo now runs the same perpetual shimmer sweep as the splash (0.1s interval, skipped when hidden on narrow terminals) (by JARVIS <jarvis@jarvis.local>)
- tool call/result callbacks now mutate the UI exclusively through the app-thread bridge (call_from_thread) - no more worker-thread DOM races that could drop tool messages (by JARVIS <jarvis@jarvis.local>)
- status spinner re-arms ("thinking...") after every tool result, so multi-round turns never look stalled between tools (by JARVIS <jarvis@jarvis.local>)
- tool labels truncate per-arg (48ch) and overall (110ch); result summary capped at 60ch - long bash commands no longer wrap the whole panel (by JARVIS <jarvis@jarvis.local>)

## [0.6.7] - 2026-08-15

### Fixed
- _md_inline docstring raw-string (invalid escape \[ -> DeprecationWarning noise) (by JARVIS <jarvis@jarvis.local>)

## [0.6.6] - 2026-08-15

### Fixed
- fix brand tagline markup (double-bracket [[dim]] -> [dim]) - MarkupError on startup (by JARVIS <jarvis@jarvis.local>)

## [0.6.5] - 2026-08-15

### Changed
- feat(tui): replace pixel whale with JARVIS brand — big-font logo + tagline in main view, splash shows shimmering JARVIS title + "microkernel · everything is a plugin" (by JARVIS <jarvis@jarvis.local>)

## [0.6.4] - 2026-08-15

### Fixed
- fix splash tagline markup (double-bracket [[dim]] -> [dim]) - MarkupError on startup (by JARVIS <jarvis@jarvis.local>)

## [0.6.3] - 2026-08-15

### Fixed
- escape literal brackets in all dynamic text (user msgs, code blocks, tool args/results, thinking, confirm prompts) so Rich markup never raises MarkupError (by JARVIS <jarvis@jarvis.local>)

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
