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
from jarvis.types import ChatChunk, ChatMessage, ChatRequest, ToolCall


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

    # provider-stub (test double that routes to a tool on the word 'tool')
    _write_plugin(
        plugins, "provider-stub", "provider",
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
        "        for m in req.messages:\n"
        "            if m.role=='tool':\n"
        "                yield ChatChunk(text='[echo] got tool result: '+m.content); return\n"
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
        "config-core", "provider-stub", "memory-jsonl"
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
    # edit provider-stub's plugin.py -> signature changes -> reload
    plugin_dir = kernel.manager.plugins["provider-stub"].path
    py = plugin_dir / "plugin.py"
    original = py.read_text()
    py.write_text(original + "\n# touched for hot reload\n")
    # bump mtime to be safe on filesystems with coarse granularity
    import os
    os.utime(py, None)
    reloaded = kernel.run_hot_reload_check()
    assert "provider-stub" in reloaded
    # tool table still intact after reload
    assert "demo.ping" in kernel._tools

def test_provider_failure_returns_error_text(kernel: Kernel) -> None:
    """A failing provider must degrade to error text, not crash the caller."""
    class _BadProvider:
        kind = "provider"

        def chat(self, req):
            raise RuntimeError("boom")

    kernel._provider_svc = _BadProvider()
    out = kernel.chat("sess-bad", "hi")
    assert "provider failed" in out
    assert "boom" in out


def test_invoke_tool_uses_snapshot(kernel: Kernel) -> None:
    """Tool dispatch goes through the round snapshot, never the live table."""
    out = kernel._invoke_tool(ToolCall(name="demo.ping", arguments={"note": "x"}), {})
    assert out == "[error] unknown tool: demo.ping"
    # a snapshot dict entry is dispatched correctly
    spec = kernel._tools["demo.ping"]
    out2 = kernel._invoke_tool(
        ToolCall(name="demo.ping", arguments={"note": "x"}), {"demo.ping": spec}
    )
    assert out2 == "pong: x"


def test_memory_roundtrip_preserves_tool_calls(kernel: Kernel, tmp_path: Path, monkeypatch) -> None:
    """The real memory-jsonl plugin keeps tool_calls + reasoning across save/load."""
    import importlib.util
    import sys

    plugin_root = Path(__file__).resolve().parents[1] / "plugins" / "memory-jsonl"
    monkeypatch.setenv("JARVIS_DATA", str(tmp_path / "data"))
    spec = importlib.util.spec_from_file_location("memory_jsonl_under_test", plugin_root / "plugin.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    m = mod._JsonlMemory()

    msgs = [
        ChatMessage(role="user", content="hi"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "call_x", "type": "function", "function": {"name": "demo.ping", "arguments": "{}"}}
            ],
            reasoning_content="think",
        ),
        ChatMessage(role="tool", content="pong", name="demo.ping"),
    ]
    m.save("sess-tc", msgs)
    loaded = m.load("sess-tc")
    assert loaded[1].tool_calls == msgs[1].tool_calls
    assert loaded[1].reasoning_content == "think"
    assert loaded[2].name == "demo.ping"

def test_self_context_injected_as_system_message(kernel: Kernel) -> None:
    """A self service's system_prompt is injected at the front of every request."""
    class _Self:
        kind = "self"

        def system_prompt(self) -> str:
            return "I am JARVIS. tools: demo.ping"

    kernel._register_service("self", _Self(), "test")

    seen = {}

    class _Spy:
        kind = "provider"

        def chat(self, req):
            seen["first"] = req.messages[0]
            yield ChatChunk(text="[echo] hi")

    kernel._provider_svc = _Spy()
    out = kernel.chat("sess-self", "hello")
    assert out == "[echo] hi"
    assert seen["first"].role == "system"
    assert "demo.ping" in seen["first"].content


def test_state_snapshot_lists_tool_descriptions(kernel: Kernel) -> None:
    """Snapshot tools carry descriptions from the live routing table."""
    s = kernel._state_snapshot()
    tools = {t["name"]: t for t in s["tools"]}
    assert "demo.ping" in tools
    assert tools["demo.ping"]["description"]


def test_state_snapshot_redacts_secret_config_keys(kernel: Kernel) -> None:
    """Config view lists keys but never secret-bearing keys."""
    kernel.set_config({
        "model": "m",
        "openai_api_key": "sk-abc",
        "ha_token": "tok",
        "ha_base_url": "http://x",
    })
    s = kernel._state_snapshot()
    assert "model" in s["config_keys"]
    assert "ha_base_url" in s["config_keys"]
    assert "openai_api_key" not in s["config_keys"]
    assert "ha_token" not in s["config_keys"]


