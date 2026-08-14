# Changelog — mdcat-render

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- md.render / md.render_file tools wrapping the mdcat CLI (soft dependency; ANSI stripped by default, ansi=true opt-in) (by JARVIS <jarvis@jarvis.local>)
- render service: channel-terminal buffered mode renders replies through mdcat when this plugin is loaded (by JARVIS <jarvis@jarvis.local>)
