"""Tests for the memory-sql plugin: SQLite history + facts, JSONL migration.

The plugin must be a drop-in memory backend (load/append/save + facts + the
mem.* tools) and migrate legacy memory-jsonl data from every candidate root
(data_dir, JARVIS_DATA, cwd) idempotently.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from jarvis.kernel import Kernel

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def kernel(tmp_path: Path, monkeypatch) -> Kernel:
    monkeypatch.chdir(tmp_path)  # cwd is a candidate migration root
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    shutil.copytree(_ROOT / "plugins" / "memory-jsonl", plugins / "memory-jsonl")
    shutil.copytree(_ROOT / "plugins" / "memory-sql", plugins / "memory-sql")
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / "data"))
    k.load()
    return k


def test_memory_sql_takes_over_backend(kernel: Kernel) -> None:
    """memory-sql sorts after memory-jsonl and wins the memory service."""
    assert type(kernel._memory_svc).__name__ == "_SqlMemory"
    mod = sys.modules["jarvis_plugin_memory_sql"]
    assert mod._ACTIVE is kernel._memory_svc


def test_history_roundtrip(kernel: Kernel) -> None:
    from jarvis.types import ChatMessage

    svc = kernel._memory_svc
    svc.append("s1", ChatMessage(role="user", content="hi"))
    svc.append("s1", ChatMessage(role="assistant", content="hello", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]))
    loaded = svc.load("s1")
    assert [m.role for m in loaded] == ["user", "assistant"]
    assert loaded[1].tool_calls[0]["id"] == "c1"
    # save() overwrites the whole session
    svc.save("s1", [ChatMessage(role="user", content="only")])
    assert [m.content for m in svc.load("s1")] == ["only"]
    # sessions are independent
    assert svc.load("other") == []


def test_consecutive_duplicates_dropped_on_load(kernel: Kernel) -> None:
    from jarvis.types import ChatMessage

    svc = kernel._memory_svc
    svc.append("s", ChatMessage(role="user", content="dup"))
    svc.append("s", ChatMessage(role="user", content="dup"))
    svc.append("s", ChatMessage(role="user", content="real"))
    assert [m.content for m in svc.load("s")] == ["dup", "real"]


def test_tool_round_assistant_messages_not_collapsed(kernel: Kernel) -> None:
    """Regression: consecutive assistant messages with empty content but
    DIFFERENT tool_calls (multi-round tool turns) must survive load().
    The old (role, content, name) dedupe key collapsed them, orphaning
    their tool results and 400-ing the upstream on replay."""
    from jarvis.types import ChatMessage

    svc = kernel._memory_svc
    svc.save("t", [
        ChatMessage(role="user", content="work"),
        ChatMessage(role="assistant", content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}}]),
        ChatMessage(role="tool", content="pong", name="a"),
        ChatMessage(role="assistant", content="", tool_calls=[{"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}}]),
        ChatMessage(role="tool", content="pong2", name="b"),
        ChatMessage(role="assistant", content="done"),
    ])
    loaded = svc.load("t")
    tc_msgs = [m for m in loaded if m.tool_calls]
    assert len(tc_msgs) == 2, [m.tool_calls for m in tc_msgs]
    assert [m.tool_calls[0]["id"] for m in tc_msgs] == ["c1", "c2"]
    assert [m.content for m in loaded if m.role == "assistant"] == ["", "", "done"]


def test_identical_consecutive_tool_results_both_survive(kernel: Kernel) -> None:
    """Regression: two DIFFERENT calls returning the SAME text are two
    separate tool rows - dedupe must never touch tool rows (each one
    is paired to a tool_call_id on replay)."""
    from jarvis.types import ChatMessage

    svc = kernel._memory_svc
    svc.save("t", [
        ChatMessage(role="user", content="work"),
        ChatMessage(role="assistant", content="", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}}, {"id": "c2", "type": "function", "function": {"name": "a", "arguments": "{}"}}]),
        ChatMessage(role="tool", content="pong", name="a"),
        ChatMessage(role="tool", content="pong", name="a"),  # identical to the previous row
        ChatMessage(role="assistant", content="done"),
    ])
    loaded = svc.load("t")
    tool_rows = [m for m in loaded if m.role == "tool"]
    assert len(tool_rows) == 2, tool_rows
    # plain-text dedupe still works
    svc.save("u", [
        ChatMessage(role="user", content="dup"),
        ChatMessage(role="user", content="dup"),
    ])
    assert [m.content for m in svc.load("u")] == ["dup"]


def test_facts_store_recall_forget(kernel: Kernel) -> None:
    svc = kernel._memory_svc
    assert svc.recall_all() == ""
    svc.store_fact("color", "blue")
    svc.store_fact("color", "red")  # overwrite keeps one row
    svc.store_fact("city", "beijing")
    facts = svc.recall_facts()
    assert {f["key"] for f in facts} == {"color", "city"}
    assert next(f["value"] for f in facts if f["key"] == "color") == "red"
    assert "color: red" in svc.recall_all()
    assert svc.forget_fact("color") is True
    assert svc.forget_fact("color") is False
    assert svc.recall_facts() == [{"key": "city", "value": "beijing", "ts": facts[0]["ts"]}] or len(svc.recall_facts()) == 1


def test_mem_tools_registered(kernel: Kernel) -> None:
    for name in ("mem.store", "mem.recall", "mem.forget", "mem.status", "mem.migrate"):
        assert name in kernel._tools, name
    assert kernel._tools["mem.store"].handler("k", "v") == "[mem] stored 'k'"
    assert "k: v" in kernel._tools["mem.recall"].handler()
    assert "sqlite" in kernel._tools["mem.status"].handler()
    assert "migration" in kernel._tools["mem.migrate"].handler().lower()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def test_migrates_history_from_cwd(kernel: Kernel, tmp_path: Path) -> None:
    """Legacy sessions live in cwd (the old memory-jsonl DATA_ROOT bug)."""
    _write_jsonl(tmp_path / "sessions" / "legacy1.jsonl", [
        {"role": "user", "content": "legacy hi"},
        {"role": "assistant", "content": "legacy answer", "reasoning_content": "think"},
    ])
    _write_jsonl(tmp_path / "sessions" / "bad.jsonl", [
        {"role": "weird", "content": "x"},  # unknown role -> skipped
        "not-json",
    ])
    _write_jsonl(tmp_path / "memory" / "facts.jsonl", [
        {"key": "legacy_fact", "value": "yes", "ts": 1},
        {"key": "legacy_fact", "value": "no", "ts": 2},  # later row wins? no: INSERT OR IGNORE keeps FIRST
    ])
    k2 = Kernel(plugins_dir=str(tmp_path / "plugins"), data_dir=str(tmp_path / "data2"))
    k2.load()
    svc = k2._memory_svc
    msgs = svc.load("legacy1")
    assert [m.content for m in msgs] == ["legacy hi", "legacy answer"]
    assert msgs[1].reasoning_content == "think"
    assert svc.load("bad") == []  # only valid rows imported
    facts = svc.recall_facts()
    assert any(f["key"] == "legacy_fact" and f["value"] == "yes" for f in facts)


def test_migration_idempotent_and_incremental(kernel: Kernel, tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "sessions" / "a.jsonl", [{"role": "user", "content": "one"}])
    svc = kernel._memory_svc
    first = svc.migrate()
    assert first["sessions"] == 1 and first["messages"] == 1
    # re-run: nothing new, nothing duplicated
    second = svc.migrate()
    assert second["sessions"] == 0 and second["merged_messages"] == 0
    assert len(svc.load("a")) == 1
    # new file picked up on a later run
    _write_jsonl(tmp_path / "sessions" / "b.jsonl", [{"role": "user", "content": "two"}])
    third = svc.migrate()
    assert third["sessions"] == 1 and third["messages"] == 1
    assert len(svc.load("b")) == 1


def test_migration_from_data_dir_root(kernel: Kernel, tmp_path: Path) -> None:
    """Sessions under data_dir are also imported (root #1)."""
    _write_jsonl(tmp_path / "data" / "sessions" / "indir.jsonl", [{"role": "user", "content": "in data dir"}])
    svc = kernel._memory_svc
    svc.migrate()
    assert [m.content for m in svc.load("indir")] == ["in data dir"]


def test_teardown_closes_db(kernel: Kernel) -> None:
    mod = sys.modules["jarvis_plugin_memory_sql"]
    mod.teardown(None)
    assert mod._ACTIVE is None


def test_merge_existing_session_prepends_older_rows(kernel: Kernel, tmp_path: Path) -> None:
    """A session already in SQL whose JSONL file holds OLDER rows (the JSONL
    froze when the backend switched): missing rows are merged in front,
    duplicates are skipped, order stays chronological."""
    from jarvis.types import ChatMessage

    svc = kernel._memory_svc
    # SQL already has the NEWER rows
    svc.append("t", ChatMessage(role="user", content="newer question"))
    svc.append("t", ChatMessage(role="assistant", content="newer answer"))
    # JSONL holds the OLDER history + one overlapping row
    _write_jsonl(tmp_path / "sessions" / "t.jsonl", [
        {"role": "user", "content": "hello jarvis"},
        {"role": "assistant", "content": "older answer"},
        {"role": "user", "content": "newer question"},  # duplicate of SQL row
    ])
    stats = svc.migrate()
    assert stats["merged_sessions"] == 1
    assert stats["merged_messages"] == 2  # only the two older rows
    loaded = svc.load("t")
    assert [m.content for m in loaded] == [
        "hello jarvis", "older answer", "newer question", "newer answer",
    ]
    # idempotent on re-run
    again = svc.migrate()
    assert again["merged_messages"] == 0
    assert len(svc.load("t")) == 4
