# cache-core

面向 LLM 调用的**透明响应缓存** - 省 token 的关键插件。内核在每次调用 provider 之前
先询问本插件;命中缓存时直接重放已存的分块,完全跳过 provider 调用(及其 token 消耗)。

- **kind**: `tool`(注册 `cache` 服务)
- **provides**: 不提供工具;提供 `cache` 服务(get/put/stats/clear)

## 如何省 token

* **精确请求缓存** - 指纹覆盖 model + 完整消息列表 + 工具表,完全相同的请求绝不会
  第二次打到 LLM。
* **前缀稳定性** - 配合 plugin-self 注入,系统提示在插件/工具集不变时逐字节一致,
  上游上下文缓存(如 DeepSeek prompt cache)会持续命中同一前缀,命中 token 更便宜。
* **错误永不缓存** - 只有以 `done=True` 结尾的完整响应才会被存储,因此修好 API key
  后立刻生效。

## 配置(config.toml)

```toml
[cache]
enabled = true      # 设为 false 可整体关闭
ttl_seconds = 300   # 条目存活秒数
max_entries = 64    # LRU 上限
```

## 统计

`cache.stats()` 返回 hits/misses/hit_rate/entries - 可以接进工具或日志,直观看到省了多少。
