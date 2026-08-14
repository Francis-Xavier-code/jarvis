# config-core

"配置即插件"的实证。持有 `config.toml`,并通过内核的 `ConfigApi`
(`kernel.config.get` / `.watch`) 暴露给所有其他插件。

> English docs: [README.md](README.md)

- **kind**: `config`
- **provides**: 一个 config *服务*(不是工具)
  - `get(key, default=None)` —— 读取一个配置值
  - `watch(key, cb)` —— 订阅某个 `key` 的变化
  - `snapshot()` —— 返回整个配置字典

## 配置

从项目根目录读取 `config.toml`(或 `JARVIS_CONFIG` 指定的路径)。任何键值都允许
(自由格式 —— 见 PLUGIN_SPEC §3.3 / §8)。示例:

```toml
model = "gpt-4o-mini"
ha_base_url = "http://homeassistant.local:8123"
ha_token = "eyJ...long-lived-token"
```

## 为什么它是一个插件

编辑 `config.toml` 会改变它的 mtime → 内核热重启这个插件(teardown + reload)→
监听者被触发。所以**配置遵守的是和其他所有能力完全相同的热重启契约**——配置不过
是另一个插件。

## 安装

这是内置在 `plugins/config-core/` 的核心插件。如需单独拉取:

```
jarvis install <your-fork-url>/jarvis-config-core
```
