# memory-jsonl

按会话存储的对话历史,以纯 JSONL 形式保存。极简、无额外依赖、调用之间无状态
(在热重启下安全)。

> English docs: [README.md](README.md)

- **kind**: `memory`
- **provides**: 一个 memory *服务*(不是工具)
  - `load(session) -> list[ChatMessage]` —— 重放某个会话的历史
  - `append(session, msg)` —— 追加一条消息

## 存储

```
$JARVIS_DATA/sessions/<session>.jsonl
```

`<session>` 会被清洗(仅保留字母数字 + `-_`),以防止路径穿越。每一行是一个 JSON
对象 `{"role", "content", "name"}`。

## 说明

- 每个会话一个文件;历史由 agent 循环在每一轮重新加载。
- 不暴露任何工具 —— 本插件只为内核的 memory 服务提供支撑。
- 想换成 `memory-sqlite` 或任何其它后端,只需写一个 `kind = "memory"` 且暴露同样
  两个方法的插件即可。
