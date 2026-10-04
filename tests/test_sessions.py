"""会话持久化：多次运行共享上下文，并且跨进程存活。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import Harness, HarnessConfig
from harness.runs_index import list_sessions
from harness.sessions import (
    COMPACTION_PREFIX,
    InvalidSessionId,
    open_conversation,
    validate_session_id,
)
from harness.testing import ScriptedModel, text_response


def make_config(tmp_path: Path) -> HarnessConfig:
    return HarnessConfig(workspace=tmp_path / "ws", runs_dir=tmp_path / "runs")


def write_run(runs_dir: Path, run_id: str, goal: str, session_id: str | None = None):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    payload = {
        "goal": goal,
        "session_id": session_id,
        "final_output": "ok",
        "last_agent": "supervisor",
        "duration_s": 1.0,
        "model_calls": 1,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "transcript": [],
        "spans": [],
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


@pytest.mark.parametrize("good", ["demo", "task-1", "a.b_c", "X" * 64])
def test_validate_session_id_accepts_reasonable_names(good):
    assert validate_session_id(good) == good


@pytest.mark.parametrize(
    "bad", ["", "-lead", ".lead", "has space", "a/b", "../x", "X" * 65, "中文"]
)
def test_validate_session_id_rejects_bad_names(bad):
    with pytest.raises(InvalidSessionId):
        validate_session_id(bad)


def test_open_conversation_creates_db(tmp_path):
    db = tmp_path / "nested" / "sessions.db"

    open_conversation("demo", db)

    assert db.is_file()


async def test_session_carries_history_across_runs(tmp_path):
    model = ScriptedModel(
        [text_response("第一次回答", "r1"), text_response("第二次回答", "r2")]
    )
    harness = Harness(make_config(tmp_path), model=model)

    await harness.run("第一句话", session_id="demo")
    await harness.run("第二句话", session_id="demo")

    second_input = json.dumps(model.calls[1]["input_items"], ensure_ascii=False)
    assert "第一句话" in second_input
    assert "第一次回答" in second_input
    assert "第二句话" in second_input


async def test_without_session_runs_stay_isolated(tmp_path):
    model = ScriptedModel(
        [text_response("回答一", "r1"), text_response("回答二", "r2")]
    )
    harness = Harness(make_config(tmp_path), model=model)

    await harness.run("第一句话")
    await harness.run("第二句话")

    # 没有会话时，第二次调用只应该看到本次输入
    assert len(model.calls[1]["input_items"]) == 1


async def test_history_survives_a_new_harness_instance(tmp_path):
    """真正的持久化：换一个 Harness 实例（相当于重启进程）还能接上历史。"""
    config = make_config(tmp_path)

    first = Harness(config, model=ScriptedModel([text_response("回答一", "r1")]))
    await first.run("第一句话", session_id="demo")

    second_model = ScriptedModel([text_response("回答二", "r2")])
    second = Harness(config, model=second_model)
    await second.run("第二句话", session_id="demo")

    carried = json.dumps(second_model.calls[0]["input_items"], ensure_ascii=False)
    assert "第一句话" in carried
    assert "回答一" in carried


async def test_old_history_is_compacted_without_touching_storage(tmp_path):
    conversation = open_conversation("demo", tmp_path / "sessions.db", max_items=5)
    items = [
        {"role": "user", "content": "原始目标：修好分页逻辑"},
        {"role": "assistant", "content": "第一次回答"},
        {"role": "user", "content": "第二个要求"},
        {"role": "assistant", "content": "第二次回答"},
        {"role": "user", "content": "最新要求"},
        {"role": "assistant", "content": "最新回答"},
    ]
    await conversation.add_items(items)

    visible = await conversation.get_items()
    assert len(visible) == 5
    assert visible[0]["role"] == "user"
    assert visible[0]["content"].startswith(COMPACTION_PREFIX)
    assert "原始目标：修好分页逻辑" in visible[0]["content"]
    assert visible[-1] == items[-1]

    # 折叠只影响模型看到的内容，原始历史一条都不能少。
    stored = await conversation.inner.get_items()
    assert stored == items


async def test_compaction_can_be_disabled(tmp_path):
    conversation = open_conversation("demo", tmp_path / "sessions.db", max_items=0)
    items = [{"role": "user", "content": f"第 {index} 条"} for index in range(12)]
    await conversation.add_items(items)

    assert await conversation.get_items() == items


async def test_compaction_does_not_start_with_an_orphan_tool_output(tmp_path):
    conversation = open_conversation("demo", tmp_path / "sessions.db", max_items=3)
    items = [
        {"role": "user", "content": "目标"},
        {"type": "function_call", "call_id": "c1", "name": "read_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "第一份输出"},
        {"type": "function_call", "call_id": "c2", "name": "read_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c2", "output": "第二份输出"},
        {"role": "assistant", "content": "阶段总结"},
        {"type": "function_call_output", "call_id": "missing", "output": "孤立的旧输出"},
        {"type": "function_call", "call_id": "c3", "name": "read_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c3", "output": "第三份输出"},
    ]
    await conversation.add_items(items)

    visible = await conversation.get_items()

    assert visible[0]["content"].startswith(COMPACTION_PREFIX)
    # 截取点必须从 function_call 开始，不能把 c3 的输出单独留在开头。
    assert visible[1]["type"] == "function_call"
    assert visible[1]["call_id"] == "c3"


async def test_harness_session_uses_the_compacted_view(tmp_path):
    config = make_config(tmp_path).with_overrides(session_item_limit=3)
    model = ScriptedModel(
        [
            text_response("回答一", "r1"),
            text_response("回答二", "r2"),
            text_response("回答三", "r3"),
        ]
    )
    harness = Harness(config, model=model)

    await harness.run("原始目标", session_id="demo")
    await harness.run("第二句话", session_id="demo")
    await harness.run("第三句话", session_id="demo")

    third_input = json.dumps(model.calls[2]["input_items"], ensure_ascii=False)
    assert COMPACTION_PREFIX in third_input
    assert "原始目标" in third_input
    assert "第二句话" in third_input
    assert "回答二" in third_input


async def test_run_payload_records_session_id(tmp_path):
    harness = Harness(make_config(tmp_path), model=ScriptedModel([text_response("ok")]))

    outcome = await harness.run("带会话的任务", session_id="demo")

    assert outcome.session_id == "demo"
    payload = json.loads((outcome.run_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["session_id"] == "demo"


async def test_invalid_session_id_is_rejected_when_running(tmp_path):
    harness = Harness(make_config(tmp_path), model=ScriptedModel([text_response("ok")]))

    with pytest.raises(InvalidSessionId):
        await harness.run("任务", session_id="../坏名字")


def test_list_sessions_groups_runs(tmp_path):
    write_run(tmp_path, "20260101-090000", "第一轮", "alpha")
    write_run(tmp_path, "20260101-120000", "第二轮", "alpha")
    write_run(tmp_path, "20260101-110000", "独立任务")
    write_run(tmp_path, "20260101-100000", "另一个会话", "beta")

    sessions = {item.session_id: item for item in list_sessions(tmp_path)}

    assert set(sessions) == {"alpha", "beta"}  # 无会话的运行不计入
    assert sessions["alpha"].run_count == 2
    assert sessions["alpha"].title == "第一轮"  # 标题取最早那次的目标
    assert sessions["alpha"].total_tokens == 30
    # 最近活跃的会话排在前面
    assert list_sessions(tmp_path)[0].session_id == "alpha"


async def test_close_releases_the_sqlite_wal_files(tmp_path):
    """不 close 会留下 -wal / -shm，长驻进程里就是句柄泄漏。"""
    config = make_config(tmp_path)
    harness = Harness(config, model=ScriptedModel([text_response("ok")]))
    await harness.run("任务", session_id="demo")

    wal = Path(str(config.sessions_db) + "-wal")
    assert wal.exists(), "连接开着时 SQLite 应该有 -wal"

    harness.close()

    assert not wal.exists(), "关闭后 -wal 应该被回收"


async def test_close_is_idempotent_and_session_can_be_reopened(tmp_path):
    config = make_config(tmp_path)
    model = ScriptedModel([text_response("回答一", "r1"), text_response("回答二", "r2")])
    harness = Harness(config, model=model)

    await harness.run("第一次", session_id="demo")
    harness.close()
    harness.close()  # 重复关闭不该报错

    # 关掉之后再用，应该从磁盘重新打开，历史不能丢
    await harness.run("第二次", session_id="demo")

    carried = json.dumps(model.calls[1]["input_items"], ensure_ascii=False)
    assert "第一次" in carried


async def test_context_manager_closes_on_exit(tmp_path):
    config = make_config(tmp_path)
    with Harness(config, model=ScriptedModel([text_response("ok")])) as harness:
        await harness.run("任务", session_id="demo")

    assert not Path(str(config.sessions_db) + "-wal").exists()
