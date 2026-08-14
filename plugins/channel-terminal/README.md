# channel-terminal

A minimal terminal REPL channel. Registers a `channel` service; the kernel's
`chat` subcommand calls `channel.run(kernel)`.

> 中文文档: [README.zh.md](README.zh.md)

- **kind**: `channel`
- **provides**: a channel *service* (`_TerminalChannel.run`)

## What it does about Markdown

The LLM replies in **Markdown** — which Telegram renders natively but a plain
terminal cannot. Presentation is this channel's job, so it translates the
Markdown into something readable:

- **TTY (a real terminal)**: renders with ANSI — bold headings, colored
  bullets, fenced code blocks. If `rich` is installed it is used for even
  nicer output.
- **non-TTY / piped / `NO_COLOR` set**: strips Markdown markers and prints
  plain text, so logs and pipes stay clean.

The renderer (`render.py`) is **stdlib-only** — `rich` is optional. The channel
is hot-reloadable like every plugin.

## Usage

```
jarvis chat
```

```
JARVIS (terminal channel). Type 'exit' to quit.
you> hello jarvis
jarvis> I'm JARVIS, your microkernel assistant — ask me anything, or call a tool.
you> exit
```

- Type `exit` or `quit` to quit.
- Hot-reloadable: edit this plugin's files and the kernel reloads it without
  restarting the process.

## Fallback

If no `channel-terminal` (or any `kind = "channel"`) plugin is present, the
kernel falls back to a built-in REPL so `jarvis chat` still works.
