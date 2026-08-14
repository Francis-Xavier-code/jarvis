# JARVIS 插件规范(v1.0 —— 已冻结)

这是**插件作者**与 **JARVIS 微内核**之间的契约。只要遵守它,任何 git 仓库在
被克隆的那一刻就能成为一个可用的 JARVIS 插件——不需要改内核,也不需要特殊注册。
内核通过扫描 `plugins/<dir>/plugin.toml` 来发现插件;其余一切皆由此派生。

> English docs: [PLUGIN_SPEC.md](PLUGIN_SPEC.md)

> **v1.0 已冻结。** 所有此前待定的决策现已确定(见 §8)。未来的变更以版本号发布
> (v1.1、v2.0 ……)。标注 **[GAP]** 的条目属于"已声明但尚未实现",将在后续版本中补齐。

---

## 1. 目录布局

插件是 `plugins/` 下的一个目录:

```
plugins/<dir>/
├── plugin.toml      # 必填 —— 清单(manifest)
├── plugin.py        # 必填 —— 入口文件(文件名取自 manifest 的 `entry`)
├── README.md        # 必填 —— 插件自身的文档(见 §7.1)
└── <other files>   # 其他任何辅助代码
```

- `<dir>` 是**克隆/磁盘名**(来自 git URL 或 `name` 覆盖值)。它可以和清单里的
  `name` 不同;加载完成后,内核以清单中的 `name` 作为插件的键。
- 被克隆的插件会带有一个 `.jarvis-cloned` 标记并被 gitignore(它们是运行时拉取
  的,绝不作为源码提交)。

---

## 2. 清单 —— `plugin.toml`

TOML,且只能有一个 `[plugin]` 表:

| 字段 | 类型 | 必填 | 默认值 | 含义 |
|------|------|------|--------|------|
| `name` | string | 是 | — | 规范的插件 id;在所有已加载插件中必须唯一 |
| `kind` | string | 是 | — | 取 `provider` \| `memory` \| `channel` \| `config` \| `tool` 之一 |
| `version` | string | 否 | `"0.0.0"` | 类似 semver,仅供说明 |
| `entry` | string | 否 | `"plugin.py"` | 目录内的入口文件名 |
| `hot_reload` | bool | 否 | `true` | 若为 false,内核不会在文件变更时自动重载它 |
| `dependencies` | list | 否 | `[]` | **[GAP]** 已声明但内核不会自动安装(见 §6) |
| `provides` | table | 否 | `{}` | 说明性:列出该插件暴露的工具/服务名 |

示例:

```toml
[plugin]
name = "jarvis-homeassistant"
kind = "tool"
version = "0.1.0"
entry = "plugin.py"
hot_reload = true

[provides]
tools = ["hass.light_on", "hass.light_off", "hass.status"]
```

无效的清单会被跳过(记录在 `manager._load_errors`,由 `jarvis bootstrap` 展示)。

---

## 3. 入口 —— `plugin.py`

必须定义:

```python
from jarvis.types import KernelApi

def setup(kernel: KernelApi) -> None:
    # 在此注册工具 和/或 服务
    ...

def teardown(kernel: KernelApi) -> None:
    # 可选;在热重启或卸载前调用
    ...
```

### 3.1 注册工具

```python
@kernel.tool("hass.light_on", "Turn on a light", {"entity_id": {"type": "string"}})
def light_on(entity_id: str) -> str:
    return f"turned on {entity_id}"
```

- 工具 `name` **按约定加命名空间**:用插件名做前缀(`hass.*`、`demo.*`)以避免冲突。
  内核不强制这一点,但同名会相互覆盖。
- 被装饰的函数接收的是 LLM 的 tool_call 中**已经解析好的关键字参数**,且必须返回
  **`str`**(内核会对返回值做 `str()`)。**v1.0 规则:工具返回类型仅限 `str`。**
  结构化(dict/JSON)返回推迟到后续版本。
- 参数 schema 在 v1.0 中是**宽松**的:一个类 JSON-schema 的字典,原样透传给 LLM。
  严格校验是后续要加的内容。

### 3.2 注册服务(按 `kind`)

```python
class _EchoProvider:
    kind = "provider"
    def chat(self, req): ...

kernel.service("provider", _EchoProvider())
```

每种 `kind` 同时只激活一个服务(最后注册的生效)。`kind` 必须与清单里的 `kind`
一致,插件才有意义:

| kind | 期望的服务接口 |
|------|----------------|
| `provider` | `.chat(req) -> iterable[ChatChunk]`(见 §5) |
| `memory` | `.load(session) -> list[ChatMessage]`,`.append(session, msg)`,`.save(session, messages)`(可选) |
| `channel` | `.run(kernel)`(阻塞式 REPL/循环) |
| `config` | `.snapshot() -> dict`,`.get(key, default)` |
| `self` | 可选:`.system_prompt() -> str`,注入到每一轮 provider 请求的最前面(见 §3.4) |
| `tool` | 不需要服务(只注册工具即可) |

### 3.3 读取配置

```python
cfg = kernel.config          # ConfigApi
token = cfg.get("ha_token", "")
cfg.watch("ha_token", lambda k, v: ...)   # 可选的变化钩子
```

配置由 `config` 插件(`config-core`)持有;其他插件通过这个 API 读取。
**v1.0 规则:配置是自由格式** —— `get`/`watch`,没有强制 schema。如需校验,
那是 config 插件自己的事。

### 3.4 自我认知服务(`kind = \"self\"`)

插件可以注册一个 `self` 服务,暴露 `.system_prompt() -> str`。若存在,内核会把该字符串
作为 `system` 消息前置到**每一轮** provider 请求(每轮重新生成、永不持久化),让模型把
自己的身份、已加载插件和可调用工具作为*先验知识*——不需要"想起来"调用工具才知道自己
能干什么。`plugin-self` 是参考实现。

---

> **memory `save`(可选):** `.save(session, messages)` 一次性全量覆盖会话历史。
> 内核在每一轮对话结束时优先调用它,以便工具调用轮与 `reasoning_content` 忠实持久化、
> 下一轮原样回放。没有 `save` 时,内核回退为只追加 user + 最终 assistant 消息。

---

## 4. 生命周期与热重启

1. **加载**:内核导入 `entry`,调用 `setup(KernelApi)`。工具/服务被注册到内核的全局表。
2. **热重启**:`PluginManager` 监视每个插件目录的 mtime/内容变化。一旦变化,先调用
   `teardown`(若存在),注销该插件的工具/服务,重新导入,再调用 `setup`——
   **不重启进程**。
3. **在途安全**:每一轮对话都取一份工具表的*快照*,因此一轮对话中途发生的重载
   只会影响下一轮,绝不会打断正在进行的对话。
4. **卸载**:`teardown` → 注销 → 从注册表中移除。

> **[GAP]** 监视器目前是手动调用的(`kernel.run_hot_reload_check()`)。计划改用
> 后台线程 / 文件监听来自动驱动。

---

## 5. Provider 协议(针对 `kind = provider`)

provider 插件的 `.chat(req)` 是一个**同步生成器**,产出 `ChatChunk`:

```python
from jarvis.types import ChatChunk, ChatRequest, ToolCall

def chat(self, req: ChatRequest):
    yield ChatChunk(text="thinking...")
    yield ChatChunk(tool_call=ToolCall(name="hass.status", arguments={"entity_id": "x"}))
```

- `ChatRequest` 携带 `messages`、`tools`(快照)、`model`。
- 一个 chunk 可携带 `text` 和/或 `tool_call`。内核收集文本,并把任何 `tool_call`
  路由到已注册的工具,结果回灌,如此重复,直到某一轮不再产生 tool_call(最多 4 轮)。
- **tool_call_id 绑定:** 解析模型的 `tool_calls` 时,把上游 id 填入 `ToolCall.id`。
  内核会把它存到 assistant 消息上;provider 必须把每条 `role:"tool"` 结果绑定到产生
  它的那条 assistant 调用的 id(**按历史顺序配对**,绝不按名字),这样同一工具被多次调用
  也不会串号。
- **v1.0 规则:provider 的 `chat` 是同步的。** `async def chat` 推迟到后续版本
  (计划与第一个真实的 HTTP/LLM provider 一起引入)。agent 循环在 v1.0 中是同步的。

---

## 6. 依赖

v1.0 中 `plugin.toml` 里的 `dependencies` **已声明但内核不会执行**——内核
**不会** `pip install` 任何东西。v1.0 下有两种安全做法:

- 只用**核心依赖**(click、pydantic、tomllib)。
- **软导入**额外依赖并优雅降级,例如 HA 示例里写的
  `try: import requests except ImportError: requests = None`,并在工具被调用时
  给出清晰的"缺少依赖"提示。

> **v1.0 规则:绝不自动安装插件依赖。** 这是刻意的安全 + YAGNI 取舍(避免在克隆时
> 引入供应链/网络风险)。需要额外包的插件必须写进文档,并依赖软导入 + 清晰的运行时
> 提示。自动安装可在后续版本中以显式 opt-in 开关重新考虑。

---

## 6.5 安装期安全(v1.0 加固)

克隆一个仓库并加载它,意味着其 `plugin.py` **在进程内**被执行——即以用户权限运行
任意代码。两道防线:

* **助手发起的安装被设闸。** `jarvis.install_plugin` 工具(经由 `PluginApi.install_from_url`)
  只接受 **http(s)** git URL,并且需要**用户明确确认**(默认交互式 `y/N` 提示;
  可通过 `kernel.confirm_install` 替换)。CLI 的 `jarvis install` 是用户有意执行的动作,
  跳过确认提示。
* **克隆目录名走白名单**(`[A-Za-z0-9_-]`,且以字母/数字开头)——`name` 或 URL 中的
  路径穿越会在任何 git 命令执行前被拒绝。git 子进程带 60 秒超时。

---

## 7. 编写检查清单

要让一个仓库可以被克隆为 JARVIS 插件:

- [ ] 根目录有合法的 `plugin.toml`,含 `[plugin]`(`name`、`kind`)
- [ ] `entry` 文件定义了 `setup(kernel)`(以及可选的 `teardown`)
- [ ] 工具用唯一、带命名空间的名字注册
- [ ] 任何额外导入都做了软导入(因为依赖不会被自动安装)
- [ ] 配置通过 `kernel.config` 读取,不在源码里硬编码密钥
- [ ] 工具函数返回 `str`
- [ ] **存在 `README.md`**,说明插件是什么、暴露了什么、如何配置/使用(见 §7.1)

这就是全部契约。**用 `jarvis install <url>` 拉取,或在 `plugin-sources.toml` 中
登记后用 `jarvis bootstrap` 拉取。**

### 7.1 插件 README(必填)

每个插件都要自带**自己的** `README.md`,让用户无需读源码就知道它是干什么的。
至少应覆盖:

- **是什么** —— 一段话说明用途。
- **kind + 暴露面** —— `kind`,以及它注册的所有工具/服务,含签名和一句话描述。
  工具签名应与 `plugin.py` 中实际的 `@kernel.tool(...)` 调用保持一致。
- **配置** —— 它读取哪些配置键(或环境变量),附示例。
- **依赖** —— 用户可能需要安装的软导入包。
- **安装** —— 如何拉取(`jarvis install <url>` 或 `plugin-sources.toml`)。
- **安全提示** —— 尤其是会执行代码、访问网络或克隆其他仓库的插件。

内置的 7 个插件(`config-core`、`provider-openai`、`memory-jsonl`、`channel-terminal`、
`jarvis-install`、`jarvis-homeassistant`、`plugin-self`)各自都含一份遵循本模板的
`README.md`。

---

## 8. v1.0 已冻结的决策

| 主题 | v1.0 规则 |
|------|-----------|
| 工具返回类型 | 仅 `str`(内核对结果做 `str()`) |
| Provider `chat` | 同步生成器(v1.0 为 sync) |
| 插件依赖 | **不自动安装**;软导入 + 清晰提示 |
| 配置 | 自由格式 `get`/`watch`,无强制 schema |
| 安装安全 | 助手安装:仅 http(s) + 用户确认;目录名白名单 |
| 记忆持久化 | 优先全量 `save`;`append` 兜底 |

本文档其余部分描述的是内核截至 v1.0 实际强制的行为。未来的变更以新的规范版本
(v1.1、v2.0 ……)发布,除非显式标注为破坏性变更,否则向后兼容。
### 7.2 CHANGELOG 与版本管理(必填)

每个插件在根目录必须带一份 **CHANGELOG.md**,并且**每次修改插件都必须同时做两件事**:

1. 在 CHANGELOG.md 中加一条记录 —— `## [<新版本号>] - <日期>`,内含
   `### Added / Changed / Fixed / Removed` 分类说明改动内容;
2. bump plugin.toml 里的 `version`(语义化:修复 → patch,新功能 → minor)。

`plugin.log_change(plugin, note, kind)` 工具(agent-tools)可以自动完成这两步,
并用 JARVIS 身份盖章条目。`jarvis doctor` 会检查每个插件是否都有 CHANGELOG.md,
以及版本号与最新 changelog 条目是否一致。

