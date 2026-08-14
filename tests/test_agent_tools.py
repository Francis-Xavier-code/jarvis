"""Tests for the agent-tools plugin (bash + filesystem tools).

The plugin registers tools against a real Kernel; tests exercise the tool
handlers directly (confirmation auto-approved unless stated otherwise).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jarvis.kernel import Kernel


@pytest.fixture
def tools(tmp_path: Path, monkeypatch) -> Kernel:
    monkeypatch.chdir(tmp_path)  # project root for fs.* tools
    src = Path(__file__).resolve().parents[1] / "plugins" / "agent-tools"
    plugins = tmp_path / "plugins"
    shutil.copytree(src, plugins / "agent-tools")
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    k.load()
    k.confirm_action = lambda prompt: True  # auto-approve by default
    return k


def _h(tools: Kernel, name: str):
    return tools._tools[name].handler


def test_bash_execute(tools: Kernel) -> None:
    out = _h(tools, "bash.execute")("echo hello")
    assert "hello" in out
    assert "exit 0" in out


def test_bash_requires_confirmation(tools: Kernel) -> None:
    tools.confirm_action = lambda prompt: False
    out = _h(tools, "bash.execute")("echo nope")
    assert "not confirmed" in out


def test_fs_write_read_edit_append(tools: Kernel) -> None:
    w, rd = _h(tools, "fs.write"), _h(tools, "fs.read")
    ed, ap = _h(tools, "fs.edit"), _h(tools, "fs.append")
    assert "wrote" in w("hello.txt", "hello world")
    assert rd("hello.txt") == "hello world"
    ed("hello.txt", "world", "JARVIS")
    assert rd("hello.txt") == "hello JARVIS"
    ap("hello.txt", "!")
    assert rd("hello.txt") == "hello JARVIS!"


def test_fs_edit_requires_unique_match(tools: Kernel) -> None:
    w, ed = _h(tools, "fs.write"), _h(tools, "fs.edit")
    w("dup.txt", "x x x")
    out = ed("dup.txt", "x", "y")
    assert "matched 3 times" in out


def test_fs_refuses_config_toml(tools: Kernel) -> None:
    out = _h(tools, "fs.read")("config.toml")
    assert "off-limits" in out
    out2 = _h(tools, "fs.write")("config.toml", "nope")
    assert "off-limits" in out2


def test_fs_outside_root_requires_confirmation(tools: Kernel, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret")
    tools.confirm_action = lambda prompt: False
    out = _h(tools, "fs.read")(str(outside))
    assert "not confirmed" in out
    tools.confirm_action = lambda prompt: True
    assert _h(tools, "fs.read")(str(outside)) == "secret"
    outside.unlink()


def test_fs_undo_restores_backup(tools: Kernel) -> None:
    w, rd, un = _h(tools, "fs.write"), _h(tools, "fs.read"), _h(tools, "fs.undo")
    w("note.txt", "version 1")
    w("note.txt", "version 2 (broken)")
    assert rd("note.txt") == "version 2 (broken)"
    assert "restored" in un("note.txt")
    assert rd("note.txt") == "version 1"


def test_fs_glob_and_list(tools: Kernel, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("y")
    out = _h(tools, "fs.glob")("**/*.py")
    assert "a.py" in out and "b.py" in out
    assert "a.py" in _h(tools, "fs.list")("")


def test_fs_write_refuses_protected_dirs(tools: Kernel, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    out = _h(tools, "fs.write")(".git/HEAD", "x")
    assert "refused" in out

def test_reload_failure_keeps_old_tools(tools: Kernel) -> None:
    """A broken edit to the agent-tools plugin must not kill its tools."""
    plugin = tools.manager.plugins["agent-tools"]
    py = plugin.path / "plugin.py"
    original = py.read_text()
    py.write_text("this is not valid python !!!")
    ok = tools.manager.reload("agent-tools")
    assert ok is False
    assert "bash.execute" in tools._tools  # rolled back, capability survives
    py.write_text(original)  # fix the file
    assert tools.manager.reload("agent-tools") is True
    assert "bash.execute" in tools._tools


def test_kernel_confirm_refuses_when_no_handler(tools: Kernel) -> None:
    tools.confirm_action = None
    assert tools.confirm("run this?") is False

