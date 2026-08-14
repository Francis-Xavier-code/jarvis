# Changelog — channel-terminal

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- REPL channel with readline history (persisted to data/history.txt)
- multi-line input (backslash continuation + paste detection)
- streaming output with tool-call announcements
- hotkeys: Ctrl-C interrupt, Ctrl-D exit, /help /exit
- tool completion feedback (check/x + duration)
- JARVIS_SHOW_REASONING opt-in thinking chain display

