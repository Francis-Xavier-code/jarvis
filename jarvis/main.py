"""JARVIS command-line entrypoint.

Subcommands:
  bootstrap   auto-clone every repo in plugin-sources.toml, then load plugins
              (one-shot setup; use `jarvis watch` to keep hot-reload running)
  install     clone one git repo into plugins/ and hot-load it (on demand)
  stats       aggregate token usage / cache hits from the request log
  doctor      health-check deps, config, plugins and the data dir
  chat        run the terminal channel (REPL); hot-reload watcher runs in background
  watch       load plugins and run ONLY the hot-reload watcher (no channel)
  telegram    run the telegram channel (deferred plugin; no-op until present)
"""
from __future__ import annotations

import os
from pathlib import Path

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
    click.echo("[jarvis] bootstrap complete — run `jarvis chat` or `jarvis watch` to start")


@cli.command()
def watch() -> None:
    """Load plugins and run only the hot-reload watcher (no channel)."""
    kernel = _make_kernel()
    _load_with_sources(kernel)
    loaded = sorted(kernel.manager.plugins.keys())
    click.echo(f"[jarvis] loaded plugins: {loaded}")
    kernel.start_hot_reload_watcher()
    click.echo("[jarvis] hot-reload watcher running. Press Ctrl-C to stop.")
    try:
        import time

        while True:
            time.sleep(1)
    except (KeyboardInterrupt, EOFError):
        kernel.stop_hot_reload_watcher()
        click.echo("\n[jarvis] watcher stopped.")


@cli.command()
@click.argument("git_url")
@click.option("--name", default=None, help="Plugin name (defaults to repo name)")
def install(git_url: str, name: str | None) -> None:
    """Clone GIT_URL into plugins/ and hot-load it."""
    kernel = _make_kernel()
    kernel.manager.install_sources(SOURCES_TOML)  # ensure sources present
    kernel.load()
    try:
        n = kernel.install_plugin(git_url, name)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"[jarvis] install failed: {exc}", err=True)
        raise click.exceptions.Exit(1)
    click.echo(f"[jarvis] installed plugin '{n}' from {git_url}")


@cli.command()
def stats() -> None:
    """Show token usage and cache-hit statistics from the request log."""
    kernel = _make_kernel()
    kernel.load()
    logger = kernel._services.get("logger")
    if logger is None:
        click.echo("[jarvis] log-stats plugin not loaded; no logs recorded yet")
        raise click.exceptions.Exit(1)
    s = logger.stats()
    if s.get("requests", 0) == 0:
        click.echo("[jarvis] no requests logged yet")
        return
    click.echo(f"requests:           {s['requests']}")
    click.echo(f"prompt tokens:      {s['prompt_tokens']}")
    click.echo(f"completion tokens:  {s['completion_tokens']}")
    click.echo(f"total tokens:       {s['total_tokens']}")
    click.echo(f"cache hits:         {s['cache_hits']} ({s['cache_hit_rate'] * 100:.1f}%)")
    click.echo("by model:")
    for model, tokens in sorted(s["by_model"].items()):
        click.echo(f"  {model}: {tokens} tokens")


@cli.command()
def doctor() -> None:
    """Health-check the JARVIS installation (deps, config, plugins, data dir)."""
    import importlib.util

    ok = True

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        if not condition:
            ok = False
        click.echo(f"[{'ok' if condition else '!!'}] {label}" + (f" - {detail}" if detail else ""))

    check("requests (web/agent tools)", importlib.util.find_spec("requests") is not None)

    kernel = _make_kernel()
    try:
        os.makedirs(kernel.data_dir, exist_ok=True)
        probe = os.path.join(kernel.data_dir, ".doctor-write-test")
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)
        check(f"data dir writable ({kernel.data_dir})", True)
    except OSError as exc:
        check("data dir writable", False, str(exc))

    kernel.load()
    if kernel.manager._load_errors:
        for name, err in kernel.manager._load_errors.items():
            check(f"plugin {name}", False, err)
    else:
        check(f"plugins loaded ({len(kernel.manager.plugins)})", True)

    po = kernel._config.get("provider-openai", {})
    key = po.get("openai_api_key") if isinstance(po, dict) else kernel._config.get("openai_api_key", "")
    check("provider API key configured", bool(key), "set [provider-openai] openai_api_key in config.toml" if not key else "present (value hidden)")

    # plugin changelog/versioning compliance
    import re
    import tomllib

    missing_cl, version_mismatch = [], []
    n_plugins = 0
    for p in sorted(Path("plugins").glob("*/")):
        toml_path = p / "plugin.toml"
        if not toml_path.exists():
            continue
        n_plugins += 1
        cl_path = p / "CHANGELOG.md"
        if not cl_path.exists():
            missing_cl.append(p.name)
            continue
        try:
            version = tomllib.loads(toml_path.read_text(encoding="utf-8"))["plugin"].get("version")
        except Exception:  # noqa: BLE001
            version = None
        m = re.search(r"\[(\d+\.\d+\.\d+)\]", cl_path.read_text(encoding="utf-8"))
        cl_version = m.group(1) if m else None
        if version and cl_version and version != cl_version:
            version_mismatch.append(f"{p.name} (toml {version} vs changelog {cl_version})")
    check("plugin CHANGELOGs present", not missing_cl, ", ".join(missing_cl) if missing_cl else f"{n_plugins} plugins")
    check("plugin versions match changelogs", not version_mismatch, "; ".join(version_mismatch) if version_mismatch else "")

    click.echo("")
    if ok:
        click.echo("JARVIS looks healthy")
    else:
        click.echo("JARVIS has problems — see [!!] items above")
        raise click.exceptions.Exit(1)


@cli.command()
def chat() -> None:
    """Run the terminal REPL channel."""
    kernel = _make_kernel()
    _load_with_sources(kernel)
    kernel.start_hot_reload_watcher()
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
