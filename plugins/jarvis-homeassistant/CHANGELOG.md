# Changelog — jarvis-homeassistant

All notable changes to this plugin are recorded here together with the version
from plugin.toml. **Every change MUST add an entry here AND bump the version
in plugin.toml** (patch for fixes, minor for new features). Use the
plugin.log_change tool to do this automatically.

## [0.1.1] - 2026-08-15

### Changed
- feat(hass): dual-mode lights - pure-local mode (state in data_dir/lights.json, zero external services) when no Home Assistant configured; REST mode when [homeassistant] ha_base_url/ha_token set; fix config keys to dotted form (homeassistant.*) (by JARVIS <jarvis@jarvis.local>)

## [0.1.0] - 2026-08-15

### Added
- hass.light_on / hass.light_off / hass.status REST API tools
- config via [homeassistant] ha_base_url / ha_token

