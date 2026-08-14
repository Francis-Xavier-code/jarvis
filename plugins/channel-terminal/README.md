# channel-terminal

A minimal terminal REPL channel. Registers a `channel` service; the kernel's
`chat` subcommand calls `channel.run(kernel)`.

- **kind**: `channel`
- **provides**: a channel *service* (`_TerminalChannel.run`)

## Usage

```
jarvis chat
```

```
JARVIS (terminal channel). Type 'exit' to quit.
you> hello jarvis
jarvis> [echo] hello jarvis
you> exit
```

- Type `exit` or `quit` to quit.
- Hot-reloadable: edit this plugin's files and the kernel reloads it without
  restarting the process.

## Fallback

If no `channel-terminal` (or any `kind = "channel"`) plugin is present, the
kernel falls back to a built-in REPL so `jarvis chat` still works.
