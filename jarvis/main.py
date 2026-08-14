"""JARVIS command-line entrypoint.

Subcommands:
  bootstrap   auto-clone every repo in plugin-sources.toml, then load plugins
  install     clone one git repo into plugins/ and hot-load it (on demand)
  chat        run the terminal channel (REPL)
  telegram    run the telegram channel (deferred plugin; no-op until present)
"""
from __future__ import annotations

import os

import click

from .kernel import Kernel

SOURCES_TOML = os.environ.get("JARVIS_SOURCES", "plugin-sources.toml")


def _make_kernel() -> Kernel:
    plugins_dir = os.environ.get("JARVIS_PLUGINS") or os.path.join(
        os.getcwd(), "plugins"
    )
    data_dir = os.environ.get(
        "JARVIS_DATA", os.path.expanduser("~/Library/Application Support/jarvis")
    )
    kernel = Kernel(plugins_dir=plugins_dir, data_dir=data_dir)
    return kernel


def _load_with_sources(kernel: Kernel) -> list[str]:
    cloned = kernel.manager.install_sources(SOURCES_TOML)
    kernel.load()
    return cloned


@click.group()
def cli() -> None:
    """JARVIS — microkernel AI assistant. Everything is a plugin."""


@cli.command()
def bootstrap() -> None:
    """Auto-clone repos from plugin-sources.toml, then load all plugins."""
    kernel = _make_kernel()
    cloned = _load_with_sources(kernel)
    if cloned:
        click.echo(f"[jarvis] cloned sources: {sorted(cloned)}")
    loaded = sorted(kernel.manager.plugins.keys())
    click.echo(f"[jarvis] loaded plugins: {loaded}")
    if kernel.manager._load_errors:
        for name, err in kernel.manager._load_errors.items():
            click.echo(f"[jarvis] plugin '{name}' error: {err}", err=True)


@cli.command()
@click.argument("git_url")
@click.option("--name", default=None, help="Plugin name (defaults to repo name)")
def install(git_url: str, name: str | None) -> None:
    """Clone GIT_URL into plugins/ and hot-load it."""
    kernel = _make_kernel()
    kernel.manager.install_sources(SOURCES_TOML)  # ensure sources present
    kernel.load()
    n = kernel.install_plugin(git_url, name)
    click.echo(f"[jarvis] installed plugin '{n}' from {git_url}")


@cli.command()
def chat() -> None:
    """Run the terminal REPL channel."""
    kernel = _make_kernel()
    _load_with_sources(kernel)
    channel = None
    for svc in kernel._channels:
        if getattr(svc, "kind", "") == "terminal":
            channel = svc
            break
    if channel is None:
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
