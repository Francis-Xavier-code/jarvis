# Changelog — config-core

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.0] - 2026-08-15

### Added
- config-as-plugin: holds config.toml, exposes get/watch via ConfigApi
- dotted-path access into TOML sections (provider-openai.key)
- hot-reload on config.toml edit

