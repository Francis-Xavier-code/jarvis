# channel-terminal

一个极简的终端 REPL 通道。它注册一个 `channel` 服务;内核的 `chat` 子命令
会调用 `channel.run(kernel)`。

> 中文文档: [README.zh.md](README.zh.md)

- **kind**: `channel`
- **provides**: 一个通道 *服务*(`_TerminalChannel.run`)

## 它如何处理 Markdown

LLM 的回复是 **Markdown** —— Telegram 能原生渲染,但普通终端不能。呈现
是通道的职责,所以它会把 Markdown 翻译成可读的形式:

- **TTY(真实终端)**:用 ANSI 渲染 —— 粗体标题、带色项目符号、围栏代码块。
  若装了 `rich` 则用 rich,效果更好。
- **非 TTY / 管道 / 设置了 `NO_COLOR`**:剥离 Markdown 标记,输出纯文本,
  保证日志和管道干净。

渲染器(`render.py`)**仅依赖标准库** —— `rich` 是可选的。该通道和所有插件
一样支持热重载。

## 用法

```
jarvis chat
```

```
JARVIS (终端通道)。输入 'exit' 退出。
you> hello jarvis
jarvis> 我是 JARVIS,你的微内核助手 —— 有什么尽管问,或调用工具。
you> exit
```

- 输入 `exit` 或 `quit` 退出。
- 支持热重载:修改本插件文件,内核会在不重启进程的情况下重新加载。

## 兜底

如果 `channel-terminal`(或任何 `kind = "channel"`)插件不存在,内核会回退到
内置 REPL,保证 `jarvis chat` 仍可用。
