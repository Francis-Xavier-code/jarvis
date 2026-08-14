# plugin-self

JARVIS 的**自我认知**插件。两个层面:

1. **系统提示服务**(`kind = "self"`)—— 内核在**每一轮** provider 请求的最前面注入一份
   实时生成的身份 + 能力摘要(已加载插件、当前 provider/model、每个可调用工具及其描述)。
   于是 JARVIS *天生知道*自己是谁、能做什么,不需要"想起来"去查询 —— 热重启或新装插件后,
   下一轮对话立刻生效。该提示每轮重新生成,**永不持久化**。
2. **`self.*` 工具** —— 供 LLM(和你)按需查询细节:

- **kind**: `tool`(另注册 `self` 服务)
- **provides**:
  - `self.whoami` —— 一段话身份说明(名字、架构、provider/model、数量)
  - `self.capabilities` —— 列出所有已加载插件和所有已路由工具,**含描述**
  - `self.version` —— 内核 + 插件规范版本
  - `self.config` —— 当前已设置的配置键(密钥脱敏)

因为它直接检查内核,所以在 `jarvis.install_plugin` 之后调用 `self.capabilities`,
会立刻看到刚加进来的工具 —— 整个闭环是"活的"。

## 示例

```
you> 你能干什么?
jarvis> [系统提示里已自带能力摘要;调用 self.capabilities 获取详情]
        JARVIS loaded plugins: ... Callable tools (name: description): ...
```

## 安全

`self.config` 只报告键的*名字*;名字包含 `api_key` / `token` / `secret` / `password`
的键,其值永远不会被展示。
