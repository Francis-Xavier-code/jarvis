# JARVIS

> 一个微内核 AI 助手,核心理念是**一切皆插件**。

> English docs: [README.md](README.md)

JARVIS 只有一条原则:内核几乎什么都不做。LLM provider、记忆后端、对话通道(终端 / telegram / web),**甚至配置本身**,全都是*插件*。每个插件是 `plugins/` 下的一个普通目录,里面包含一个 `plugin.toml` 清单和一个 `plugin.py` 入口。

插件向内核注册工具(tools)和服务(services)。内核把它们聚合成一张统一的工具表并运行 agent 循环。插件支持**热重启**:改动插件的文件(或其配置),内核会把它卸载(teardown)再重新加载——不需要重启进程,而且正在进行的对话是安全的,因为每一轮对话都使用工具表的快照。

## 目录结构

```
jarvis/            # 微内核(types、插件管理器、kernel、cli)
plugins/           # 所有能力都以普通子目录的形式放在这里
  config-core/     # 配置即插件(持有 config.toml,暴露 get/watch)
  provider-openai/ # 真实 LLM 大脑(OpenAI 兼容;默认 = opencodego 聚合商)
  memory-jsonl/    # 按会话存储的对话历史(JSONL)
  channel-terminal/# 终端 REPL 通道
  jarvis-install/  # 拉取能力,暴露为插件
  jarvis-homeassistant/ # 示例:证明"克隆 -> 可用插件"的 HA 包装器
  plugin-self/     # 自我认知(whoami / capabilities / version)
```

## 运行

```bash
uv venv && uv pip install -e .
uv run jarvis chat        # 终端 REPL
uv run jarvis bootstrap   # 列出已加载的插件 + 任何加载错误
```

## 写一个插件

创建 `plugins/my-thing/plugin.toml`:

```toml
[plugin]
name = "my-thing"
kind = "tool"            # provider | memory | channel | config | tool
version = "0.1.0"
entry = "plugin.py"
hot_reload = true
```

以及 `plugins/my-thing/plugin.py`:

```python
from jarvis.types import KernelApi

def setup(kernel: KernelApi) -> None:
    @kernel.tool("my_thing.greet", "Greet someone", {"name": {"type": "string"}})
    def greet(name: str = "world") -> str:
        return f"hello, {name}"
```

把文件夹放进 `plugins/`,下次启动时就会被加载(或者你一编辑文件就立即热重启)。不需要改内核。

## 路线图(机制完成之后)

- 真实的 `provider-*` 插件(兼容 OpenAI 的端点)
- `channel-telegram`(长轮询 bot)与 `channel-web`
- `tool-homeassistant` 示例插件
- 可选:把部分插件提升为独立的 git 仓库并支持自动拉取
