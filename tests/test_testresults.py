"""测试结果的解析与「越改越糟」检测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import Harness, HarnessConfig
from harness.runs_index import previous_test_result
from harness.runner import resume_turn_budget
from harness.testing import ScriptedModel, text_response, tool_call_response
from harness.testresults import (
    ResultTracker,
    failure_count,
    parse_test_summary,
)


@pytest.mark.parametrize(
    "text,passed,failed,errors",
    [
        ("13 failed, 112 passed in 2.44s", 112, 13, 0),
        ("151 passed in 18.18s", 151, 0, 0),
        ("1 failed, 2 passed, 1 error in 0.5s", 2, 1, 1),
        ("2 failed, 123 passed, 1 warning in 5.23s", 123, 2, 0),
    ],
)
def test_parse_pytest_summaries(text, passed, failed, errors):
    result = parse_test_summary(text)
    assert result is not None
    assert (result["passed"], result["failed"], result["errors"]) == (
        passed,
        failed,
        errors,
    )


def test_parse_takes_the_last_summary_line():
    """pytest 会在结尾再打一次汇总，中间那句可能是旧信息。"""
    text = (
        "1 failed, 10 passed in 0.1s\n"
        "... 中间一堆输出 ...\n"
        "2 failed, 9 passed in 0.3s\n"
    )
    result = parse_test_summary(text)
    assert result is not None
    assert result["failed"] == 2


@pytest.mark.parametrize(
    "text",
    ["", "no tests ran in 0.01s", "hello world", "exit_code=0\nstdout:\n  build ok"],
)
def test_parse_returns_none_when_there_is_no_summary(text):
    assert parse_test_summary(text) is None


def test_tracker_is_quiet_on_the_first_result():
    tracker = ResultTracker()

    assert tracker.observe("pytest -q", "2 failed, 123 passed in 5s") == ""
    assert failure_count(tracker.latest) == 2


def test_tracker_warns_when_failures_grow():
    tracker = ResultTracker({"passed": 123, "failed": 2, "errors": 0})
    tracker.observe("pytest -q", "2 failed, 123 passed in 5s")

    notice = tracker.observe("pytest -q", "13 failed, 112 passed in 2s")

    assert "涨到 13" in notice
    assert "先别继续猜" in notice


def test_tracker_confirms_when_failures_shrink():
    tracker = ResultTracker({"passed": 112, "failed": 13, "errors": 0})
    tracker.observe("pytest -q", "13 failed, 112 passed in 2s")

    notice = tracker.observe("pytest -q", "125 passed in 2s")

    assert "降到 0" in notice
    assert "收敛" in notice


def test_tracker_is_quiet_when_the_count_is_unchanged():
    tracker = ResultTracker({"passed": 123, "failed": 2, "errors": 0})
    tracker.observe("pytest -q", "2 failed, 123 passed in 5s")

    assert tracker.observe("pytest -q", "2 failed, 123 passed in 5s") == ""


def test_tracker_ignores_output_without_a_summary():
    tracker = ResultTracker({"passed": 123, "failed": 2, "errors": 0})

    assert tracker.observe("make", "Compiling...\nDone.") == ""
    assert tracker.latest == {"passed": 123, "failed": 2, "errors": 0}


def test_tracker_does_not_compare_different_commands():
    """先跑单文件（20 passed）再跑全量（13 failed），范围不同，不能直接比。"""
    tracker = ResultTracker()
    tracker.observe("pytest tests/test_a.py -q", "20 passed in 1s")

    notice = tracker.observe("pytest tests/ -q", "13 failed, 112 passed in 3s")

    assert notice == "", "不同范围的测试不该报「变差了」"


def test_tracker_compares_only_the_same_command():
    tracker = ResultTracker()
    tracker.observe("pytest tests/ -q", "2 failed, 123 passed in 5s")

    notice = tracker.observe("pytest tests/ -q", "13 failed, 112 passed in 5s")

    assert "涨到 13" in notice


# ---- 连续变差就主动叫停 ----


def test_tracker_warns_first_then_stops_on_the_second_regression():
    stopped: list[bool] = []
    tracker = ResultTracker(
        {"passed": 120, "failed": 5, "errors": 0},
        previous_command="pytest -q",
        on_stop=lambda: stopped.append(True),
        regression_limit=2,
    )

    first = tracker.observe("pytest -q", "8 failed, 117 passed in 1s")
    assert "⚠" in first
    assert stopped == [], "第一次变差只该警告"

    second = tracker.observe("pytest -q", "13 failed, 112 passed in 1s")
    assert "⛔" in second
    assert stopped == [True], "第二次连续变差该叫停"
    assert tracker.stop_reason and "连续 2 次" in tracker.stop_reason


def test_an_improvement_resets_the_regression_counter():
    tracker = ResultTracker(
        {"passed": 120, "failed": 5, "errors": 0},
        previous_command="pytest -q",
        regression_limit=2,
    )

    tracker.observe("pytest -q", "8 failed, 117 passed in 1s")  # 退步 1
    tracker.observe("pytest -q", "3 failed, 122 passed in 1s")  # 好转 -> 归零
    notice = tracker.observe("pytest -q", "9 failed, 116 passed in 1s")  # 退步 1

    assert "⚠" in notice
    assert tracker.consecutive_regressions == 1
    assert tracker.stop_reason is None


def test_a_different_command_does_not_count_as_a_regression():
    """换个测试范围不算退步 —— 那只是换了个基准。"""
    tracker = ResultTracker(
        {"passed": 20, "failed": 0, "errors": 0},
        previous_command="pytest tests/test_a.py -q",
        regression_limit=2,
    )

    notice = tracker.observe("pytest tests/ -q", "13 failed, 112 passed in 3s")

    assert notice == ""
    assert tracker.consecutive_regressions == 0


# ---- 跨 resume 的记忆 ----


def _write_run(runs_dir: Path, run_id: str, payload: dict) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_previous_test_result_reads_the_run_itself(tmp_path):
    _write_run(
        tmp_path,
        "20260101-090000",
        {"test_result": {"failed": 2}, "test_command": "pytest -q"},
    )

    previous = previous_test_result(tmp_path, "20260101-090000")

    assert previous is not None
    assert previous.result == {"failed": 2}
    assert previous.command == "pytest -q"
    assert previous.regression_streak == 0


def test_previous_test_result_walks_the_resume_chain(tmp_path):
    """这一条是重点：每次 resume 都是新运行，上一次的结果只能顺着链找。"""
    _write_run(
        tmp_path,
        "20260101-090000",
        {"test_result": {"failed": 2}, "test_command": "pytest -q"},
    )
    _write_run(tmp_path, "20260101-090100", {"resumed_from": "20260101-090000"})
    _write_run(tmp_path, "20260101-090200", {"resumed_from": "20260101-090100"})

    previous = previous_test_result(tmp_path, "20260101-090200")

    assert previous is not None
    assert previous.result == {"failed": 2}
    assert previous.command == "pytest -q"


def test_previous_test_result_stops_at_the_nearest_one(tmp_path):
    _write_run(
        tmp_path,
        "20260101-090000",
        {"test_result": {"failed": 2}, "test_command": "pytest -q"},
    )
    _write_run(
        tmp_path,
        "20260101-090100",
        {
            "test_result": {"failed": 13},
            "test_command": "pytest tests/ -q",
            "resumed_from": "20260101-090000",
        },
    )

    previous = previous_test_result(tmp_path, "20260101-090100")

    assert previous is not None
    assert previous.result == {"failed": 13}
    assert previous.command == "pytest tests/ -q"


def test_previous_test_result_carries_the_regression_streak(tmp_path):
    """这一个不跨 resume 的话，永远攒不到叫停的阈值。"""
    _write_run(
        tmp_path,
        "20260101-090000",
        {
            "test_result": {"failed": 3},
            "test_command": "pytest -q",
            "regression_streak": 1,
        },
    )

    previous = previous_test_result(tmp_path, "20260101-090000")

    assert previous is not None
    assert previous.regression_streak == 1


def test_previous_test_result_survives_a_broken_link(tmp_path):
    _write_run(tmp_path, "20260101-090100", {"resumed_from": "20260101-090000"})

    assert previous_test_result(tmp_path, "20260101-090100") is None


def test_previous_test_result_handles_a_cycle(tmp_path):
    """坏数据里出现自引用也不能死循环。"""
    _write_run(tmp_path, "20260101-090000", {"resumed_from": "20260101-090000"})

    assert previous_test_result(tmp_path, "20260101-090000") is None


def test_harness_can_be_seeded_with_a_previous_result(tmp_path):
    config = HarnessConfig(workspace=tmp_path / "ws", runs_dir=tmp_path / "runs")

    harness = Harness(config, previous_test_result={"failed": 2, "passed": 123})
    try:
        assert harness.test_results.previous == {"failed": 2, "passed": 123}
    finally:
        harness.close()


async def test_run_is_cancelled_after_consecutive_regressions(tmp_path):
    """核心断言：不是提示模型，是 harness 自己叫停。"""

    # 现实里命令是同一条（pytest -q），变的只是输出。所以这里用一个会记住
    # 调用次数的小脚本：同一条命令，每次都报出更差的测试结果。
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    (workspace / "counter.py").write_text(
        "import pathlib\n"
        "p = pathlib.Path('n.txt')\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "rows = ['5 failed, 120 passed', '5 failed, 120 passed',\n"
        "        '8 failed, 117 passed', '13 failed, 112 passed']\n"
        "print(rows[min(n, len(rows) - 1)], 'in 1s')\n",
        encoding="utf-8",
    )

    def run_counter(call_id: str):
        return tool_call_response(
            "run_command", {"command": "python counter.py"}, call_id=call_id
        )

    model = ScriptedModel(
        [
            tool_call_response("coder", {"input": "跑测试"}, call_id="c0"),
            run_counter("c1"),  # 基准
            run_counter("c2"),  # 没变
            run_counter("c3"),  # 退步 1 -> 警告
            run_counter("c4"),  # 退步 2 -> 叫停
            text_response("不该跑到这里", "r1"),
        ]
    )
    config = HarnessConfig(
        workspace=tmp_path / "ws",
        runs_dir=tmp_path / "runs",
        allow_shell=True,
        routing_mode="off",
        # 关掉逐条审批，否则命令还没执行运行就先暂停了，tracker 拿不到输出
        approve_shell=False,
    )
    harness = Harness(config, model=model)
    try:
        outcome = await harness.run("修测试")
    finally:
        harness.close()

    assert outcome.status == "cancelled"
    assert outcome.stop_reason is not None
    assert "连续" in outcome.stop_reason


# ---- 续跑的回合预算 ----


def test_resume_budget_grows_with_the_accumulated_turns():
    """实测踩过：current_turn 会被一起恢复，沿用同一个 max_turns 就再也续不动。"""
    state = {"current_turn": 12, "max_turns": 12}

    assert resume_turn_budget(state, 12) == 24


def test_resume_budget_handles_a_fresh_state():
    assert resume_turn_budget({"current_turn": 0}, 12) == 12


@pytest.mark.parametrize(
    "bad",
    [{"current_turn": None}, {"current_turn": "x"}, {}],
)
def test_resume_budget_survives_bad_states(bad):
    assert resume_turn_budget(bad, 12) >= 12
