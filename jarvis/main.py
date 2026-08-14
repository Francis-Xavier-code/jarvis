"""JARVIS command-line entrypoint.

Subcommands:
  bootstrap   load all plugins from plugins/ (default behaviour on every start)
  chat        run the terminal channel (REPL)
  telegram    run the telegram channel (deferred plugin; no-op until present)
"""
from __future__ import annotations

import os
import sys

import click

from .kernel import Kernel


def _make_kernel() -> Kernel:
    DEFAULT_PLUGINS = os.environ.get("JARVIS_PLUGINS") or os.path.join(
        os.getcwd(), "plugins"
    )
    DEFAULT_DATA = os.environ.get(
        "JARVIS_DATA", os.path.expanduser("~/Library/Application Support/jarvis")
    )
    kernel = Kernel(plugins_dir=DEFAULT_PLUGINS, data_dir=DEFAULT_DATA)
    kernel.load()
    return kernel


@click.group()
def cli() -> None:
    """JARVIS — microkernel AI assistant. Everything is a plugin."""


@cli.command()
def bootstrap() -> None:
    """Discover and load every plugin under plugins/."""
    kernel = _make_kernel()
    loaded = sorted(kernel.manager.plugins.keys())
    click.echo(f"[jarvis] loaded plugins: {loaded}")
    if kernel.manager._load_errors:
        for name, err in kernel.manager._load_errors.items():
            click.echo(f"[jarvis] plugin '{name}' error: {err}", err=True)


@cli.command()
def chat() -> None:
    """Run the terminal REPL channel."""
    kernel = _make_kernel()
    channel = None
    for svc in kernel._channels:
        if getattr(svc, "kind", "") == "terminal":
            channel = svc
            break
    if channel is None:
        # fallback minimal REPL if no terminal plugin registered a channel
        click.echo("[jarvis] no terminal channel plugin; using built-in REPL")
        _builtin_repl(kernel)
        return
    channel.run(kernel)


def _builtin_repl(kernel: Kernel) -> None:
    session = "terminal"
    click.echo("JARVIS (built-in REPL). Type 'exit' to quit.")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("exit", "quit"):
            break
        if not line:
            continue
        print("jarvis>", kernel.chat(session, line))


if __name__ == "__main__":
    cli()
