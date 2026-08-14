<div align="center">

<img src="assess/jarvis-logo.png" alt="JARVIS logo" width="420">

**一个微内核 AI 助手,核心理念是*一切皆插件*。**

`jarvis` · Python ≥ 3.11 · 热重载 · 自我修改

[English](README.md) &nbsp;·&nbsp; [文档](docs/) &nbsp;·&nbsp; [变更日志](CHANGELOG.md)

</div>

---

> **唯一的原则:内核几乎什么都不做。**
> LLM provider、记忆后端、对话通道,**甚至配置本身**——全都是插件。

JARVIS 建立在这一条原则上。每个插件是 `plugins/` 下的一个普通目录,包含
`plugin.toml` 清单和 `plugin.py` 入口。插件向内核注册**工具(tools)**和
**服务(services)**,内核把它们聚合成一张统一的工具表,并运行 agent 循环。

## ✨ 特性

- 🧩 **一切皆插件** — provider、记忆、通道、配置、工具
- 🔥 **热重载** — 编辑插件(或其配置)即刻生效;进行中的对话通过工具表快照保持安全
- 🧠 **跨会话记忆** — `mem.store` / `mem.recall` 记住跨重启的事实
- 🖥️ **双通道** — readline REPL(`jarvis chat`)与全屏 TUI(`jarvis tui`)
- 📝 **Markdown 渲染 TUI** — 粗体 / 列表 / 代码块 / 链接,外加动画 JARVIS 启动页
- 🪄 **自我修改** — JARVIS 可以编辑自己的插件文件、热加载新插件,并在下一轮对话中重新接线自己
- 🌐 **联网工具** — 内置搜索与网页抓取
- 🏠 **Home Assistant** — 灯光控制示例插件(克隆 → 可用插件,一步到位)

## 🧬 架构

```
                  ┌──────────────────────────────────────────┐
                  │              JARVIS kernel               │
                  │  tool table · agent loop · plugin mgr    │
                  │  confirm gate · turn snapshots           │
                  └───▲───────────▲───────────▲───────────▲──┘
                      │ register  │ chat()    │ reload    │ get/watch
        ┌─────────────┴──┐   ┌────┴──────┐   ┌┴──────────┐ ┌┴─────────┐
        │  tool plugins  │   │ providers │   │ channels  │ │  config  │
        │ fs·web·hass·…  │   │  openai   │   │ terminal  │ │  core    │
        └────────────────┘   └───────────┘   │ tui       │ └──────────┘
                                             └───────────┘
```

## 📦 目录结构

```
jarvis/             # 微内核(types · 插件管理器 · kernel · CLI)
plugins/            # 所有能力都以普通子目录的形式存在
config.toml         # 配置(本身就是一个插件的数据)
assess/             # 设计资源(logo · banner)
tests/              # pytest 测试套件
# 运行时数据在仓库之外:~/Library/Application Support/jarvis/
#   memory/memory.db — 会话 + 事实,同一个 SQLite 库(memory-sql 插件)
```

## 🚀 快速开始

```bash
uv venv && uv pip install -e ".[ui]"   # [ui] 会拉取 TUI 所需的 textual
uv run jarvis tui                      # 全屏 TUI
uv run jarvis chat                     # 终端 REPL
uv run jarvis bootstrap                # 列出已加载插件 + 加载错误
uv run jarvis doctor                   # 环境体检
uv run jarvis install <git-url>        # 拉取插件仓库并热加载
uv run jarvis check                    # 一键回归门(编译+测试+体检)
uv run jarvis snapshot "msg"           # git 检查点;--undo 回滚
```

> **要修 JARVIS 自己?** 见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)——黄金循环:
> `jarvis check` → 修复 → `jarvis check` → `jarvis snapshot`。

## 🔌 写一个插件

`plugins/my-thing/plugin.toml`:

```toml
[plugin]
name = "my-thing"
kind = "tool"            # provider | memory | channel | config | tool
version = "0.1.0"
entry = "plugin.py"
hot_reload = true
```

`plugins/my-thing/plugin.py`:

```python
from jarvis.types import KernelApi

def setup(kernel: KernelApi) -> None:
    @kernel.tool("my_thing.greet", "Greet someone", {"name": {"type": "string"}})
    def greet(name: str = "world") -> str:
        return f"hello, {name}"
```

把文件夹丢进 `plugins/` —— 下次启动即加载,或在你编辑它的瞬间热重载。**无需改动内核。**

## 🗂️ 插件清单

| 插件 | 类型 | 作用 |
|---|---|---|
| `provider-openai` | provider | LLM 大脑(OpenAI 兼容,SSE 流式 + 工具调用) |
| `memory-jsonl` | memory | 会话历史 + 跨会话事实(JSONL) |
| `memory-sql` | memory | 同样接口换 SQLite(`memory/memory.db`,WAL,自动迁移旧 JSONL) |
| `config-core` | config | 配置即插件(`get`/`watch`,mtime 热重载) |
| `channel-terminal` | channel | readline REPL,支持粘贴检测与多行输入 |
| `channel-tui` | channel | 全屏 textual TUI:md 渲染、确认提示、工具反馈、动画启动页 |
| `web-tools` | tool | 网络搜索 + 网页抓取 |
| `agent-tools` | tool | agent 身份 + 文件 / shell 工具 |
| `cache-core` | tool | 响应缓存 |
| `log-stats` | tool | 用量与日志统计 |
| `mdcat-render` | tool | 通过 mdcat CLI 把 Markdown 渲染成 ANSI(`md.render` / `md.render_file`,为终端通道提供 `render` 服务) |
| `personality` | tool | 人格层 |
| `plugin-self` | tool | 自我认知(`whoami` / `capabilities` / `version` / `config`) |
| `jarvis-install` | tool | 运行时从 git 仓库拉取插件 |
| `jarvis-homeassistant` | tool | Home Assistant 灯光(示例:克隆 → 可用插件) |

## 🤖 "这个仓库就是你的身体?"

**基本如此。** 内核是骨架,`plugins/` 是器官,`config.toml` 是设置——而且自从
换成 memory-sql 后,**一个 SQLite 数据库(`memory/memory.db`)就是记忆中枢**:
会话与事实都存在里面,旧 JSONL 数据首次启动时自动迁移。运行中的进程是
JARVIS *清醒*;这个仓库就是 JARVIS *本身* —— 像基因组一样用 git 做版本管理,
而且可以运行中修改。

## 🗺️ 路线图

- `channel-telegram` / `channel-web` —— 远程通道
- TUI 里的 `/model` 切换与 `/resume` 会话
- 文件编辑的 diff 视图
- 把部分插件提升为独立仓库并支持自动拉取

<!-- --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 03:33:28 --- -->
