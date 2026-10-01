"""停止与续跑。

关键点：取消是**协作式**的 —— 运行会自己收尾并把状态留下来，
所以停下来的任务还能接着跑，而不是全丢。
"""

from __future__ import annotations

import signal

import pytest

from harness import Harness, HarnessConfig
from harness.cli import _run_with_cancel, _sigint_handler
from harness.progress import ProgressEvent
from harness.runner import CancelToken
from harness.runs_index import STATE_FILENAME, list_runs
from harness.testing import ScriptedModel, text_response, tool_call_response


def make_config(tmp_path, **overrides) -> HarnessConfig:
    defaults = {"workspace": tmp_path / "ws", "runs_dir": tmp_path / "runs"}
    defaults.update(overrides)
    return HarnessConfig(**defaults)


def write_script() -> ScriptedModel:
    return ScriptedModel(
        [
            tool_call_response("coder", {"input": "写文件"}, call_id="c1"),
            tool_call_response(
                "write_file", {"path": "a.txt", "content": "hi"}, call_id="c2"
            ),
            text_response("coder 完成", response_id="r1"),
            text_response("全部完成", response_id="r2"),
        ]
    )


async def test_pre_cancelled_token_stops_the_run(tmp_path):
    harness = Harness(make_config(tmp_path), model=write_script())
    token = CancelToken()
    token.cancel()

    outcome = await harness.run("写个文件", cancel_token=token)

    assert outcome.status == "cancelled"
    assert outcome.final_output == ""
    assert (outcome.run_dir / STATE_FILENAME).is_file(), "状态要留下来才能续跑"


async def test_cancelling_from_a_progress_event_also_works(tmp_path):
    """取消信号是在事件之间轮询的，所以跑起来之后也能叫停。"""
    harness = Harness(make_config(tmp_path), model=write_script())
    token = CancelToken()

    def on_event(event: ProgressEvent) -> None:
        if event.kind == "agent_start" and event.agent == "coder":
            token.cancel()

    outcome = await harness.run("写个文件", cancel_token=token, on_event=on_event)

    assert outcome.status == "cancelled"


async def test_cancelled_run_can_be_resumed(tmp_path):
    harness = Harness(make_config(tmp_path), model=write_script())
    token = CancelToken()
    token.cancel()
    cancelled = await harness.run("写个文件", cancel_token=token)

    resumed = await harness.resume(cancelled.run_id, approve=True)

    assert resumed.status == "completed"
    assert resumed.final_output == "全部完成"
    assert resumed.resumed_from == cancelled.run_id


async def test_cancelled_run_shows_up_as_cancelled_not_paused(tmp_path):
    """被停止的运行没有待批准项，不该混进「等批准」那一类。"""
    harness = Harness(make_config(tmp_path), model=write_script())
    token = CancelToken()
    token.cancel()
    await harness.run("写个文件", cancel_token=token)

    summary = list_runs(tmp_path / "runs")[0]

    assert summary.status == "cancelled"
    assert summary.pending == []


async def test_resume_clears_the_cancelled_marker(tmp_path):
    harness = Harness(make_config(tmp_path), model=write_script())
    token = CancelToken()
    token.cancel()
    cancelled = await harness.run("写个文件", cancel_token=token)

    await harness.resume(cancelled.run_id, approve=True)

    assert not (cancelled.run_dir / STATE_FILENAME).exists()
    assert list_runs(tmp_path / "runs")[-1].status == "completed"


async def test_progress_still_fires_on_the_streaming_path(tmp_path):
    """改用 run_streamed 之后，进度事件不能丢。"""
    harness = Harness(make_config(tmp_path), model=write_script())
    events: list[ProgressEvent] = []

    await harness.run("写个文件", on_event=events.append)

    agents = {e.agent for e in events if e.kind == "agent_start"}
    assert {"supervisor", "coder"} <= agents


async def test_run_without_a_token_is_unaffected(tmp_path):
    harness = Harness(make_config(tmp_path), model=write_script())

    outcome = await harness.run("写个文件")

    assert outcome.status == "completed"
    assert not (outcome.run_dir / STATE_FILENAME).exists()


def test_run_with_cancel_restores_the_signal_handler(tmp_path):
    harness = Harness(make_config(tmp_path), model=write_script())
    before = signal.getsignal(signal.SIGINT)

    try:
        _run_with_cancel(harness, "写个文件", None, True)
    finally:
        harness.close()

    assert signal.getsignal(signal.SIGINT) is before


def test_first_sigint_sets_the_cancel_token():
    """第一次 Ctrl+C 只发取消信号，不杀进程 —— 这样状态才留得住。"""
    token = CancelToken()
    handler = _sigint_handler(token, {"count": 0})

    handler(signal.SIGINT, None)

    assert token.cancelled


def test_second_sigint_forces_an_exit():
    """运行卡死时，再按一次要能强退。"""
    token = CancelToken()
    handler = _sigint_handler(token, {"count": 0})
    handler(signal.SIGINT, None)

    with pytest.raises(KeyboardInterrupt):
        handler(signal.SIGINT, None)

    signal.signal(signal.SIGINT, signal.SIG_DFL)  # 立刻恢复，别影响其他测试
