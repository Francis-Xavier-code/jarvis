# jarvis-homeassistant(示例 / 模板)

核心主张的实证:**拉取一个仓库 → 它变成一个可用的 JARVIS 插件**。本插件通过
Home Assistant 的 REST API 与它通信。

> English docs: [README.md](README.md)

- **kind**: `tool`
- **provides** 三个工具:

```
hass.light_on(entity_id: str) -> str
    打开一个灯实体,例如 "light.living_room"。

hass.light_off(entity_id: str) -> str
    关闭一个灯实体。

hass.status(entity_id: str) -> str
    获取某个实体的当前状态。
```

## 配置

通过 `config-core` 插件的 `config.toml` 设置,或使用环境变量:

| 键(config.toml) | 环境变量 | 示例 |
|-----------------|----------|------|
| `ha_base_url` | `_HA_BASE` | `http://homeassistant.local:8123` |
| `ha_token` | `_HA_TOKEN` | long-lived access token |

若未设置,工具会返回 `[hass] not configured (set ha_base_url/ha_token)`。

## 依赖

使用 `requests`(软导入)。如果你真的调用某个 `hass.*` 工具,请在 JARVIS 的 venv 里
安装一次:

```
uv pip install requests
```

## 重要说明

这是一个**模板**,不是官方的 Home Assistant 仓库。官方 HA 仓库并不遵循 JARVIS 的
`plugin.toml` 约定,因此无法直接克隆 —— 本包装器把 HA 的 REST API 适配成了 JARVIS
工具。克隆它、设置好你的配置,`hass.*` 工具就会立即可用。
