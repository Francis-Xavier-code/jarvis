"""Tests for the plugin puller: clone a git repo -> it becomes a JARVIS plugin.

Proves the core claim: "any git repo with plugin.toml can be pulled in and used
as a plugin" — no special kernel handling, just clone + discover + load.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from jarvis.kernel import Kernel


def _make_git_plugin(repo: Path, name: str, tool_name: str) -> None:
    """Create a *valid JARVIS plugin* inside a fresh git repo at ``repo``."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "plugin.toml").write_text(
        textwrap.dedent(
            f"""
            [plugin]
            name = "{name}"
            kind = "tool"
            version = "0.1.0"
            entry = "plugin.py"
            hot_reload = true
            """
        ).strip()
    )
    (repo / "plugin.py").write_text(
        "from jarvis.types import KernelApi\n"
        "def setup(kernel: KernelApi):\n"
        f"    @kernel.tool('{tool_name}', 'say hi', {{}})\n"
        "    def say_hi() -> str:\n"
        f"        return 'hi from {name}'\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


@pytest.fixture
def kernel(tmp_path: Path) -> Kernel:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    return k


def test_install_plugin_from_git(tmp_path: Path, kernel: Kernel) -> None:
    # "someone else's repo" living at a local path (stands in for a remote URL)
    remote = tmp_path / "remote-ha"
    _make_git_plugin(remote, "ha-demo", "ha_demo.status")

    # clone dir name comes from the URL ("remote-ha"); manifest name is "ha-demo"
    returned = kernel.install_plugin(str(remote))
    assert returned == "ha-demo"
    assert "ha-demo" in kernel.manager.plugins
    # the tool from the cloned repo is now in the kernel tool table
    assert "ha_demo.status" in kernel._tools
    # and it is actually callable
    spec = kernel._tools["ha_demo.status"]
    assert spec.handler is not None
    assert "hi from ha-demo" in spec.handler()


def test_install_is_idempotent(tmp_path: Path, kernel: Kernel) -> None:
    remote = tmp_path / "remote-x"
    _make_git_plugin(remote, "x-plugin", "x.ping")
    first = kernel.install_plugin(str(remote))
    second = kernel.install_plugin(str(remote))
    assert first == second == "x-plugin"
    assert "x.ping" in kernel._tools


def test_uninstall_plugin(tmp_path: Path, kernel: Kernel) -> None:
    remote = tmp_path / "remote-y"
    _make_git_plugin(remote, "y-plugin", "y.ping")
    kernel.install_plugin(str(remote))
    assert "y.ping" in kernel._tools
    ok = kernel.uninstall_plugin("y-plugin")
    assert ok is True
    assert "y.ping" not in kernel._tools
    assert "y-plugin" not in kernel.manager.plugins

def test_clone_rejects_unsafe_name(tmp_path: Path, kernel: Kernel) -> None:
    """Path-traversal plugin names are refused before any clone happens."""
    from jarvis.install import PluginInstallError

    with pytest.raises(PluginInstallError):
        kernel.install_plugin("https://example.com/repo.git", name="../../evil")
    assert not (tmp_path / "evil").exists()


def test_clone_rejects_bad_default_name(tmp_path: Path, kernel: Kernel) -> None:
    """A URL whose last path segment is unsafe must be refused too."""
    from jarvis.install import PluginInstallError

    with pytest.raises(PluginInstallError):
        kernel.install_plugin("https://example.com/..")
    # nothing was cloned into plugins/
    assert not list((tmp_path / "plugins").iterdir())


def test_install_refuses_non_http_url_for_assistant(kernel: Kernel) -> None:
    """The assistant-facing installer only accepts http(s) URLs."""
    from jarvis.types import PluginApi

    api = PluginApi(kernel)
    assert "refused" in api.install_from_url("file:///etc/passwd")
    assert "refused" in api.install_from_url("git@github.com:org/repo.git")


def test_install_requires_user_confirmation(kernel: Kernel, tmp_path: Path) -> None:
    """Assistant installs must pass the kernel confirmation gate."""
    from jarvis.types import PluginApi

    kernel.confirm_install = lambda url: False
    api = PluginApi(kernel)
    out = api.install_from_url("https://example.com/repo.git")
    assert "refused" in out and "not confirmed" in out
    assert not list((tmp_path / "plugins").iterdir())

