# personality

可配置的**人格**插件。它的 `system_prompt()` 会在每一轮 provider 请求中注入到自我认知提示
之前,让 JARVIS 无论换什么模型/provider 都保持稳定的语气与行事风格。

- **kind**: `tool`(注册 `personality` 服务)
- **provides**: 不提供工具

## 配置(config.toml)

```toml
[personality]
name = "JARVIS"
style = "简洁、温暖、带点俏皮;emoji 克制使用"
traits = "乐于助人、精确、诚实面对局限"
rules = "绝不说自己没做过的事"
```

热编辑 config.toml 即可在下一轮改变人格 —— 无需重启。
