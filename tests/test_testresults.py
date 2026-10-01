"""测试结果的解析与「越改越糟」检测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import Harness, HarnessConfig
from harness.runs_index import previous_test_result
from harness.runner import resume_turn_budget
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

    assert previous_test_result(tmp_path, "20260101-090000") == (
        {"failed": 2},
        "pytest -q",
    )


def test_previous_test_result_walks_the_resume_chain(tmp_path):
    """这一条是重点：每次 resume 都是新运行，上一次的结果只能顺着链找。"""
    _write_run(
        tmp_path,
        "20260101-090000",
        {"test_result": {"failed": 2}, "test_command": "pytest -q"},
    )
    _write_run(tmp_path, "20260101-090100", {"resumed_from": "20260101-090000"})
    _write_run(tmp_path, "20260101-090200", {"resumed_from": "20260101-090100"})

    assert previous_test_result(tmp_path, "20260101-090200") == (
        {"failed": 2},
        "pytest -q",
    )


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

    assert previous_test_result(tmp_path, "20260101-090100") == (
        {"failed": 13},
        "pytest tests/ -q",
    )


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
