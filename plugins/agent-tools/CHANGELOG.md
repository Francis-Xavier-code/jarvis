# Changelog — agent-tools

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.2.0] - 2026-08-15

### Added
- added plugin.log_change tool (CHANGELOG entry + semver bump) (by JARVIS <jarvis@jarvis.local>)

## [0.1.0] - 2026-08-15

### Added
- bash.execute - shell commands with per-command user confirmation
- fs.read / fs.write / fs.edit / fs.append / fs.list / fs.glob / fs.undo
- automatic backups before every write (data/backups/, last 5 kept)
- reload-rollback safety: a broken plugin edit never kills the capability
- edit signatures with JARVIS identity isolated from host git config
- agent.identity tool (git -c isolation hint)
- plugin.log_change tool - CHANGELOG entry + version bump per change

