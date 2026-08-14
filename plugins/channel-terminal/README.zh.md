# channel-terminal

一个极简的终端 REPL 通道。注册一个 `channel` 服务;内核的 `chat` 子命令会调用
`channel.run(kernel)`。

> English docs: [README.md](README.md)

- **kind**: `channel`
- **provides**: 一个 channel *服务*(`_TerminalChannel.run`)

## 用法

```
jarvis chat
```

```
JARVIS (terminal channel). Type 'exit' to quit.
you> hello jarvis
jarvis> [echo] hello jarvis
you> exit
```

- 输入 `exit` 或 `quit` 退出。
- 支持热重启:编辑本插件的文件,内核会在不重启进程的情况下重新加载它。

## 回退

如果没有 `channel-terminal`(或任何 `kind = "channel"`)插件,内核会回退到一个
内置的 REPL,因此 `jarvis chat` 仍然可用。
