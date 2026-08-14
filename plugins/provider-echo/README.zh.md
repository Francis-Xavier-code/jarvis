# provider-echo(桩 —— 不是真实 LLM)

一个占位用的 provider,用来证明整条链路:用户输入 → agent 循环 → 工具路由 →
记忆 → 输出 —— **且不依赖任何真实模型或 api key**。真实的 provider
(`provider-openai` 等)后续会作为独立的插件目录加入,架构不变。

> English docs: [README.md](README.md)

- **kind**: `provider`
- **provides**: 一个 provider *服务*(`_EchoProvider.chat`)**和一个**工具

## 工具

```
demo.ping(note: str = "") -> str
    返回 "pong" + 可选备注。仅用于验证工具路由。
```

## 行为

1. 回显最后一条用户消息:`[echo] <text>`。
2. 如果用户消息包含单词 **"tool"**(且历史中尚不存在工具结果),则发出一个对
   `demo.ping` 的 `tool_call`,以验证工具路由路径。
3. 在工具结果被回灌之后,它会产出一条引用该结果的最终答复
   (`[echo] got tool result: ...`)。

## 替换我

**不要**在生产中使用本插件。把它换成真实的 provider 插件(`kind = "provider"`,
实现 `.chat(req)`,它是一个同步生成器并产出 `ChatChunk` —— 见 PLUGIN_SPEC §5)。
内核无需其它改动即可接管新的 provider。
