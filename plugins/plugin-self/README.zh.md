# plugin-self

JARVIS 的**自我认知**插件。它暴露一组工具,让 LLM(和你)可以查询 JARVIS *是什么*、
当前*能做什么*。这是"我是谁"的入口 —— 它直接读取**实时**内核状态(已加载插件、
已注册工具),所以答案永远是最新的,即便刚热重启或刚装了新插件也如此。

- **kind**: `tool`
- **provides**:
  - `self.whoami` —— 一段话身份说明(名字、架构、当前 provider/model)
  - `self.capabilities` —— 列出当前已加载插件及所有已路由的工具
  - `self.version` —— 内核 + 插件规范版本

因为它直接检查内核,所以在 `jarvis.install_plugin` 之后调用 `self.capabilities`,
会立刻看到刚加进来的工具 —— 整个闭环是"活的"。

## 示例

```
you> 你是谁?
jarvis> [调用 self.whoami] 我是 JARVIS,一个"一切皆插件"的微内核 AI 助手……
        当前已加载:7 个插件,12 个工具……
```
