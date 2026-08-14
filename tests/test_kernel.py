"""Tests for the JARVIS microkernel + plugin system.

These verify the core proposition: a plain directory with plugin.toml +
plugin.py becomes a JARVIS plugin — tools register, tool calls route, memory
persists, and editing a plugin file triggers a hot-reload (no restart).
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from jarvis.kernel import Kernel
from jarvis.types import ChatChunk, ChatRequest, ToolCall


def _write_plugin(base: Path, name: str, kind: str, py: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.toml").write_text(
        textwrap.dedent(
            f"""
            [plugin]
            name = "{name}"
            kind = "{kind}"
            version = "0.1.0"
            entry = "plugin.py"
            hot_reload = true
            """
        ).strip()
    )
    (d / "plugin.py").write_text(py)
    return d


@pytest.fixture
def kernel(tmp_path: Path) -> Kernel:
    plugins = tmp_path / "plugins"
    plugins.mkdir()

    # config-core
    _write_plugin(
        plugins, "config-core", "config",
        "from jarvis.types import KernelApi\n"
        "def setup(kernel: KernelApi):\n"
        "    kernel._kernel.set_config({'model': 'stub'})\n"
        "    kernel.service('config', _C())\n"
        "class _C:\n"
        "    kind='config'\n"
        "    def snapshot(self): return {'model':'stub'}\n",
    )

    # provider-echo (stub that routes to a tool on the word 'tool')
    _write_plugin(
        plugins, "provider-echo", "provider",
        "from jarvis.types import KernelApi, ChatChunk, ToolCall\n"
        "def setup(kernel: KernelApi):\n"
        "    kernel.service('provider', _P())\n"
        "    @kernel.tool('demo.ping', 'ping', {})\n"
        "    def ping(note=''): return 'pong'+ (note and ': '+note)\n"
        "class _P:\n"
        "    kind='provider'\n"
        "    def chat(self, req):\n"
        "        last=''\n"
        "        for m in reversed(req.messages):\n"
        "            if m.role=='user': last=m.content; break\n"
        "        if 'tool' in last.lower():\n"
        "            yield ChatChunk(text='(calling) ')\n"
        "            yield ChatChunk(tool_call=ToolCall(name='demo.ping', arguments={'note':'x'}))\n"
        "            return\n"
        "        yield ChatChunk(text='[echo] '+last)\n",
    )

    # memory-jsonl
    _write_plugin(
        plugins, "memory-jsonl", "memory",
        "import json, os\n"
        "from pathlib import Path\n"
        "from jarvis.types import ChatMessage, KernelApi\n"
        "ROOT = Path(os.environ.get('JARVIS_DATA','')) or (Path(__file__).resolve().parents[2]/'data')\n"
        "def _p(s):\n"
        "    d=ROOT/'sessions'; d.mkdir(parents=True, exist_ok=True)\n"
        "    return d/f\"{(s or 'default').replace('/','_')}.jsonl\"\n"
        "def setup(kernel: KernelApi):\n"
        "    kernel.service('memory', _M())\n"
        "class _M:\n"
        "    kind='memory'\n"
        "    def load(self, s):\n"
        "        p=_p(s)\n"
        "        if not p.exists(): return []\n"
        "        out=[]\n"
        "        for line in p.read_text().splitlines():\n"
        "            if line.strip(): out.append(ChatMessage(**json.loads(line)))\n"
        "        return out\n"
        "    def append(self, s, m):\n"
        "        with _p(s).open('a') as f: f.write(json.dumps({'role':m.role,'content':m.content,'name':m.name})+chr(10))\n",
    )

    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    k.load()
    return k


def test_plugins_loaded(kernel: Kernel) -> None:
    assert set(kernel.manager.plugins.keys()) == {
        "config-core", "provider-echo", "memory-jsonl"
    }


def test_echo_chain(kernel: Kernel) -> None:
    out = kernel.chat("sess1", "hello world")
    assert out == "[echo] hello world"


def test_tool_routing(kernel: Kernel) -> None:
    out = kernel.chat("sess2", "please use a tool")
    assert "pong" in out


def test_memory_persists(kernel: Kernel) -> None:
    kernel.chat("sess3", "remember this")
    # second turn: history should contain the first user message
    hist = kernel._memory_svc.load("sess3")
    contents = [m.content for m in hist]
    assert "remember this" in contents


def test_hot_reload_on_file_change(kernel: Kernel) -> None:
    # edit provider-echo's plugin.py -> signature changes -> reload
    plugin_dir = kernel.manager.plugins["provider-echo"].path
    py = plugin_dir / "plugin.py"
    original = py.read_text()
    py.write_text(original + "\n# touched for hot reload\n")
    # bump mtime to be safe on filesystems with coarse granularity
    import os
    os.utime(py, None)
    reloaded = kernel.run_hot_reload_check()
    assert "provider-echo" in reloaded
    # tool table still intact after reload
    assert "demo.ping" in kernel._tools
