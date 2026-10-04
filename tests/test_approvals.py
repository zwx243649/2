"""审批门：危险工具在人工批准之前不能执行。

驱动这件事的真实事故：agent 自己跑了 `pip install pytest`，
把包装进了系统 Python —— 它有 shell 权限，但没人授权它装东西。
"""

from __future__ import annotations

import json

import pytest

from harness import Harness, HarnessConfig
from harness.runs_index import (
    STATE_FILENAME,
    list_pending,
    list_runs,
    load_graph_config,
)
from harness.runner import stored_execution_route
from harness.testing import ScriptedModel, text_response, tool_call_response

MARKER_CMD = "echo hi > marker.txt"


def make_config(tmp_path, **overrides) -> HarnessConfig:
    defaults = {
        "workspace": tmp_path / "ws",
        "runs_dir": tmp_path / "runs",
        "allow_shell": True,
        "routing_mode": "off",
    }
    defaults.update(overrides)
    return HarnessConfig(**defaults)


def pausing_model() -> ScriptedModel:
    """supervisor 委派给 coder，coder 想跑命令 —— 在这里被拦下。"""
    return ScriptedModel(
        [
            tool_call_response("coder", {"input": "创建 marker 文件"}, call_id="c1"),
            tool_call_response(
                "run_command", {"command": MARKER_CMD}, call_id="c2"
            ),
            text_response("命令已完成", response_id="r1"),
            text_response("全部完成", response_id="r2"),
        ]
    )


async def test_shell_command_pauses_the_run(tmp_path):
    harness = Harness(make_config(tmp_path), model=pausing_model())

    outcome = await harness.run("创建一个 marker 文件")

    assert outcome.status == "paused"
    assert outcome.final_output == ""
    assert outcome.pending and outcome.pending[0]["tool"] == "run_command"
    assert MARKER_CMD in outcome.pending[0]["arguments"]
    assert (outcome.run_dir / STATE_FILENAME).is_file()


async def test_tool_does_not_execute_before_approval(tmp_path):
    """这是整个功能的核心断言。"""
    harness = Harness(make_config(tmp_path), model=pausing_model())

    await harness.run("创建一个 marker 文件")

    assert not (tmp_path / "ws" / "marker.txt").exists()


async def test_approve_executes_the_tool_and_completes(tmp_path):
    harness = Harness(make_config(tmp_path), model=pausing_model())
    paused = await harness.run("创建一个 marker 文件")

    resumed = await harness.resume(paused.run_id, approve=True)

    assert resumed.status == "completed"
    assert resumed.final_output == "全部完成"
    assert resumed.resumed_from == paused.run_id
    assert (tmp_path / "ws" / "marker.txt").exists(), "批准后应该真的执行"
    assert not (paused.run_dir / STATE_FILENAME).exists(), "处理完要清掉待办标记"


async def test_reject_means_the_tool_never_runs(tmp_path):
    harness = Harness(make_config(tmp_path), model=pausing_model())
    paused = await harness.run("创建一个 marker 文件")

    resumed = await harness.resume(paused.run_id, approve=False)

    assert resumed.status == "completed"
    assert not (tmp_path / "ws" / "marker.txt").exists()
    assert not (paused.run_dir / STATE_FILENAME).exists()


async def test_resume_creates_a_new_run_linked_to_the_original(tmp_path):
    harness = Harness(make_config(tmp_path), model=pausing_model())
    paused = await harness.run("创建一个 marker 文件")

    resumed = await harness.resume(paused.run_id, approve=True)

    assert resumed.run_id != paused.run_id
    payload = json.loads(
        (resumed.run_dir / "run.json").read_text(encoding="utf-8")
    )
    assert payload["resumed_from"] == paused.run_id


async def test_resume_without_state_is_rejected(tmp_path):
    harness = Harness(make_config(tmp_path), model=pausing_model())
    outcome = await harness.run("创建一个 marker 文件")
    (outcome.run_dir / STATE_FILENAME).unlink()

    with pytest.raises(FileNotFoundError, match="没有可继续的状态"):
        await harness.resume(outcome.run_id, approve=True)


async def test_no_approval_needed_when_disabled(tmp_path):
    """approve_shell=False 时行为退回原样：直接执行。"""
    harness = Harness(
        make_config(tmp_path, approve_shell=False), model=pausing_model()
    )

    outcome = await harness.run("创建一个 marker 文件")

    assert outcome.status == "completed"
    assert (tmp_path / "ws" / "marker.txt").exists()


def test_list_pending_shows_unresolved_runs_only(tmp_path):
    runs_dir = tmp_path / "runs"
    for run_id, state in (
        ("20260101-090000", True),
        ("20260101-100000", False),
    ):
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(
            json.dumps(
                {
                    "goal": f"任务 {run_id}",
                    "pending": [{"tool": "run_command", "arguments": "{}"}],
                }
            ),
            encoding="utf-8",
        )
        if state:
            (run_dir / STATE_FILENAME).write_text("{}", encoding="utf-8")

    pending = list_pending(runs_dir)

    assert [item.run_id for item in pending] == ["20260101-090000"]


def test_status_is_derived_from_the_state_file(tmp_path):
    """status 从 state.json 是否存在推导，文件里存的那个值不作数。

    否则续跑之后 state.json 被删了，文件里那句 "paused" 就会一直留着说谎。
    三种情况：没状态=完成，有状态且有待批准=暂停，有状态但没待批准=被停止。
    """
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-090000"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"goal": "x", "status": "paused"}), encoding="utf-8"
    )

    # 没有 state.json，就算文件里写着 paused 也当已完成
    assert list_runs(runs_dir)[0].status == "completed"

    (run_dir / STATE_FILENAME).write_text("{}", encoding="utf-8")
    # 有状态但没有待批准项 —— 是被停止的，不是等批准
    assert list_runs(runs_dir)[0].status == "cancelled"

    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "goal": "x",
                "pending": [{"tool": "run_command", "arguments": "{}"}],
            }
        ),
        encoding="utf-8",
    )
    assert list_runs(runs_dir)[0].status == "paused"

    (run_dir / STATE_FILENAME).unlink()
    assert list_runs(runs_dir)[0].status == "completed"


def test_pending_clears_once_the_state_file_is_gone(tmp_path):
    """status 和 pending 必须一致 —— 曾经出现过「已完成却还挂着待批准」。"""
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-090000"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "goal": "x",
                "pending": [{"tool": "run_command", "arguments": "{}"}],
            }
        ),
        encoding="utf-8",
    )

    assert list_runs(runs_dir)[0].pending == []  # 没有 state.json 就不该有待办

    (run_dir / STATE_FILENAME).write_text("{}", encoding="utf-8")
    summary = list_runs(runs_dir)[0]
    assert summary.status == "paused"
    assert len(summary.pending) == 1


async def test_graph_config_is_persisted_with_the_run(tmp_path):
    harness = Harness(make_config(tmp_path), model=pausing_model())

    outcome = await harness.run("创建一个 marker 文件")

    payload = json.loads((outcome.run_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["graph_config"]["allow_shell"] is True
    assert payload["graph_config"]["approve_shell"] is True
    assert payload["graph_config"]["max_turns"] == 12
    assert payload["graph_config"]["worker_max_turns"] == 8


async def test_resume_rejects_a_mismatched_tool_config(tmp_path):
    """原运行带了 shell，续跑忘了带 —— 必须当场报错。

    不报错的话，待执行的 run_command 在新建的图里根本不存在，
    运行会永远卡在同一个暂停点，而且看不出原因。
    """
    harness = Harness(make_config(tmp_path), model=pausing_model())
    paused = await harness.run("创建一个 marker 文件")

    wrong = Harness(
        make_config(tmp_path, allow_shell=False), model=pausing_model()
    )

    with pytest.raises(ValueError, match="工具配置"):
        await wrong.resume(paused.run_id, approve=True)


def test_load_graph_config_returns_empty_for_old_records(tmp_path):
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-090000"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"goal": "老记录"}), encoding="utf-8"
    )

    assert load_graph_config(runs_dir, "20260101-090000") == {}


def test_load_graph_config_filters_non_config_metadata(tmp_path):
    """旧记录把 execution_route 混进 graph_config，恢复时不能当构造参数。"""
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-090000"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "goal": "恢复旧记录",
                "graph_config": {
                    "allow_shell": True,
                    "max_turns": 12,
                    "execution_route": "supervisor",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    stored = load_graph_config(runs_dir, "20260101-090000")

    assert "execution_route" not in stored
    assert stored["allow_shell"] is True
    assert HarnessConfig(workspace=tmp_path / "ws").with_overrides(
        **stored
    ).allow_shell is True


def test_stored_execution_route_reads_new_and_legacy_payloads():
    assert stored_execution_route({"execution_route": "coder"}) == "coder"
    assert stored_execution_route(
        {"graph_config": {"execution_route": "coder"}}
    ) == "coder"
    assert stored_execution_route({}) == "supervisor"
