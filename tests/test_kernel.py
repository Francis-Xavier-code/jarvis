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

def test_chat_consults_cache_service(kernel: Kernel) -> None:
    """The agent loop asks the cache before the provider and stores the result."""
    class _SpyCache:
        kind = "cache"

        def __init__(self):
            self.gets = 0
            self.puts = 0

        def get(self, req):
            self.gets += 1
            return None

        def put(self, req, chunks):
            self.puts += 1

    kernel._register_service("cache", _SpyCache(), "test")
    out = kernel.chat("sess-cache", "hello")
    assert out == "[echo] hello"
    svc = kernel._services["cache"]
    assert svc.gets >= 1
    assert svc.puts >= 1

def test_trim_history_keeps_recent_rounds(kernel: Kernel) -> None:
    history = []
    for i in range(5):
        history.append(ChatMessage(role="user", content=f"u{i}"))
        history.append(ChatMessage(role="assistant", content=f"a{i}"))
    trimmed = kernel._trim_history(history, 2)
    assert trimmed[0].role == "system"  # truncation note
    assert [m.content for m in trimmed[1:]] == ["u3", "a3", "u4", "a4"]


def test_trim_history_keeps_tool_with_its_round(kernel: Kernel) -> None:
    history = [
        ChatMessage(role="user", content="u0"),
        ChatMessage(role="assistant", content="", tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "demo.ping", "arguments": "{}"}}
        ]),
        ChatMessage(role="tool", content="pong", name="demo.ping"),
        ChatMessage(role="user", content="u1"),
        ChatMessage(role="assistant", content="a1"),
    ]
    trimmed = kernel._trim_history(history, 1)
    # the tool round belongs to u0 and is dropped with it; only u1+a1 survive
    assert [m.content for m in trimmed[1:]] == ["u1", "a1"]


def test_chat_trims_history_before_sending(kernel: Kernel) -> None:
    kernel.set_config({"memory": {"max_rounds": 1}})
    seen = {}

    class _Spy:
        kind = "provider"

        def chat(self, req):
            seen["n"] = len(req.messages)
            yield ChatChunk(text="[echo] ok")

    kernel._provider_svc = _Spy()
    mem = kernel._memory_svc
    for i in range(3):
        mem.append("sess-trim", ChatMessage(role="user", content=f"u{i}"))
        mem.append("sess-trim", ChatMessage(role="assistant", content=f"a{i}"))
    out = kernel.chat("sess-trim", "fresh")
    assert out == "[echo] ok"
    # truncation note + last 1 round (u2,a2) + the new user message
    assert seen["n"] == 4

def test_chat_streaming_callbacks(kernel: Kernel) -> None:
    """on_chunk fires per chunk; on_tool fires before each tool call."""
    texts: list[str] = []
    calls: list[str] = []
    out = kernel.chat(
        "sess-stream",
        "please use a tool",
        on_chunk=lambda c: texts.append(c.text or ""),
        on_tool=lambda c: calls.append(c.name),
    )
    assert "demo.ping" in calls
    assert any("pong" in t for t in texts) or "pong" in out

def test_secrets_redacted_in_reply(kernel: Kernel) -> None:
    """A configured api key echoed by the model is masked in the output."""
    kernel.set_config({"provider-openai": {"openai_api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"}})

    class _Leaky:
        kind = "provider"

        def chat(self, req):
            yield ChatChunk(text="my key is sk-abcdefghijklmnopqrstuvwxyz123456")
            yield ChatChunk(done=True)

    kernel._provider_svc = _Leaky()
    out = kernel.chat("sess-redact", "what is my key?")
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "***" in out


_ALWAYS_TOOL_STUB = (
    "from jarvis.types import KernelApi, ChatChunk, ToolCall\n"
    "N = 0\n"
    "def setup(kernel: KernelApi):\n"
    "    kernel.service('provider', _P())\n"
    "    @kernel.tool('demo.ping', 'ping', {})\n"
    "    def ping(): return 'pong'\n"
    "class _P:\n"
    "    kind='provider'\n"
    "    def chat(self, req):\n"
    "        global N\n"
    "        N += 1\n"
    "        yield ChatChunk(tool_call=ToolCall(name='demo.ping', arguments={}))\n"
    "        yield ChatChunk(done=True)\n"
)


def _tool_round_kernel(tmp_path: Path, provider_src: str) -> Kernel:
    _write_plugin(tmp_path / "plugins", "provider-stub", "provider", provider_src)
    k = Kernel(plugins_dir=str(tmp_path / "plugins"), data_dir=str(tmp_path / "data"))
    k.load()
    return k


def test_tool_round_winddown_produces_final_answer(tmp_path: Path) -> None:
    """Regression: a task needing more than 4 tool rounds used to end
    mid-flight - the last round's tools ran but the model never got to
    answer. The wind-down request now produces the final answer."""
    stub = (
        "from jarvis.types import KernelApi, ChatChunk, ToolCall\n"
        "N = 0\n"
        "def setup(kernel: KernelApi):\n"
        "    kernel.service('provider', _P())\n"
        "    @kernel.tool('demo.ping', 'ping', {})\n"
        "    def ping(): return 'pong'\n"
        "class _P:\n"
        "    kind='provider'\n"
        "    def chat(self, req):\n"
        "        global N\n"
        "        N += 1\n"
        "        if N < 5:\n"
        "            yield ChatChunk(tool_call=ToolCall(name='demo.ping', arguments={}))\n"
        "        else:\n"
        "            yield ChatChunk(text='final answer')\n"
        "        yield ChatChunk(done=True)\n"
    )
    k = _tool_round_kernel(tmp_path, stub)
    out = k.chat("s1", "work")
    assert out == "final answer"
    import sys

    assert sys.modules["jarvis_plugin_provider_stub"].N == 5  # 4 rounds + wind-down


def test_tool_round_winddown_note_when_still_calling(tmp_path: Path) -> None:
    """A provider that never stops calling tools: after 4 rounds + 1 wind-down
    the kernel streams and persists an explicit limit note - never a silent
    cut mid-task."""
    k = _tool_round_kernel(tmp_path, _ALWAYS_TOOL_STUB)
    notes: list[str] = []
    out = k.chat("s1", "work", on_chunk=lambda c: notes.append(c.text or ""))
    assert "tool-round limit reached (4)" in out
    assert any("tool-round limit" in n for n in notes)  # streamed to channels
    import sys

    assert sys.modules["jarvis_plugin_provider_stub"].N == 5


def test_tool_round_cap_configurable(tmp_path: Path) -> None:
    """[agent] max_tool_rounds configures the budget (and the wind-down)."""
    k = _tool_round_kernel(tmp_path, _ALWAYS_TOOL_STUB)
    k.set_config({"agent": {"max_tool_rounds": 2}})
    out = k.chat("s1", "work")
    assert "tool-round limit reached (2)" in out
    import sys

    assert sys.modules["jarvis_plugin_provider_stub"].N == 3  # 2 rounds + wind-down


def test_credential_shapes_redacted_without_config(kernel: Kernel) -> None:
    """Known credential shapes are masked even when not in the config."""
    class _Leaky:
        kind = "provider"

        def chat(self, req):
            yield ChatChunk(text="token: Bearer abcdefghijklmnopqrstuvwxyz1234567890")
            yield ChatChunk(done=True)

    kernel._provider_svc = _Leaky()
    out = kernel.chat("sess-redact2", "hi")
    assert "Bearer abcdefghijklmnopqrstuvwxyz1234567890" not in out
    assert "***" in out

def test_tool_done_callback_fires(kernel: Kernel) -> None:
    """on_tool_done reports each tool call's result and duration."""
    done: list[tuple] = []
    kernel.chat(
        "sess-td",
        "please use a tool",
        on_tool_done=lambda c, r, d: done.append((c.name, r, d)),
    )
    assert any(name == "demo.ping" for name, _, _ in done)
    assert all(d >= 0 for _, _, d in done)


def test_confirm_auto_approve_skips_handler(kernel: Kernel) -> None:
    """auto_approve=true approves without consulting the confirm handler."""
    kernel.set_config({"auto_approve": True})
    kernel.confirm_action = lambda prompt: False  # would refuse if consulted
    assert kernel.confirm("run dangerous command?") is True


def test_confirm_auto_approve_toggles_with_config(kernel: Kernel) -> None:
    """auto_approve reads the live config, so hot-reload toggling works."""
    kernel.confirm_action = lambda prompt: False
    assert kernel.confirm("run this?") is False
    kernel.set_config({"auto_approve": True})
    assert kernel.confirm("run this?") is True
    kernel.set_config({})
    assert kernel.confirm("run this?") is False


def test_set_auto_approve_updates_live_and_persists(kernel: Kernel) -> None:
    """set_auto_approve flips the gate now and writes through the config svc."""
    seen: list[tuple] = []

    class _Cfg:
        kind = "config"

        def set(self, key, value):
            seen.append((key, value))

    kernel._register_service("config", _Cfg(), "test")
    kernel.set_auto_approve(True)
    assert kernel.auto_approve() is True
    assert kernel.confirm("run this?") is True
    kernel.set_auto_approve(False)
    assert kernel.auto_approve() is False
    assert seen == [("auto_approve", True), ("auto_approve", False)]


def test_set_auto_approve_works_without_config_service(kernel: Kernel) -> None:
    """No config plugin loaded: still flips live, persistence is skipped."""
    kernel.set_auto_approve(True)
    assert kernel.auto_approve() is True






