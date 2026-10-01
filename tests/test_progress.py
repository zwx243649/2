"""实时进度事件的测试。

核心约束：worker 是嵌套运行，必须显式把 hooks 传进 as_tool()，
否则进度里只剩「委派」这一层，看不到 worker 内部在做什么。
"""

from __future__ import annotations

import io

from harness import Harness, HarnessConfig
from harness.progress import (
    ConsoleReporter,
    ProgressEvent,
    format_event,
    preview,
)
from harness.testing import ScriptedModel, text_response, tool_call_response


def _workspace_config(tmp_path) -> HarnessConfig:
    return HarnessConfig(workspace=tmp_path / "ws", runs_dir=tmp_path / "runs")


def _delegating_script() -> ScriptedModel:
    return ScriptedModel(
        [
            tool_call_response("coder", {"input": "写文件"}, call_id="c1"),
            tool_call_response(
                "write_file", {"path": "a.txt", "content": "hi"}, call_id="c2"
            ),
            text_response("已写入 a.txt", response_id="r1"),
            text_response("完成", response_id="r2"),
        ]
    )


async def test_nested_worker_events_are_reported(tmp_path):
    harness = Harness(_workspace_config(tmp_path), model=_delegating_script())
    events: list[ProgressEvent] = []

    await harness.run("写个文件", on_event=events.append)

    triples = [(e.kind, e.agent, e.tool) for e in events]
    assert ("agent_start", "supervisor", None) in triples
    assert ("tool_start", "supervisor", "coder") in triples
    # 这两条是关键：不把 hooks 传给 as_tool() 就收不到
    assert ("agent_start", "coder", None) in triples
    assert ("tool_start", "coder", "write_file") in triples
    assert ("agent_end", "coder", None) in triples
    assert ("agent_end", "supervisor", None) in triples

    # 委派的返回值不再单独播报 —— worker 的 agent_end 已经展示了同一份内容
    assert ("tool_end", "supervisor", "coder") not in triples


async def test_worker_events_are_indented_deeper(tmp_path):
    harness = Harness(_workspace_config(tmp_path), model=_delegating_script())
    events: list[ProgressEvent] = []

    await harness.run("写个文件", on_event=events.append)

    depths = {(e.kind, e.agent): e.depth for e in events if e.kind == "agent_start"}
    assert depths[("agent_start", "supervisor")] == 0
    assert depths[("agent_start", "coder")] == 1


async def test_emitter_is_dropped_after_the_run(tmp_path):
    """跑完必须摘掉 emitter，否则下一次运行会往旧的回调里发事件。"""
    model = _delegating_script()
    model.responses.extend([text_response("第二次完成", response_id="r3")])
    harness = Harness(_workspace_config(tmp_path), model=model)
    events: list[ProgressEvent] = []

    await harness.run("第一次", on_event=events.append)
    count_after_first = len(events)
    assert count_after_first > 0

    await harness.run("第二次")  # 不传 emitter

    assert len(events) == count_after_first


async def test_broken_emitter_does_not_break_the_run(tmp_path):
    """进度输出出错绝不能影响主流程。"""
    harness = Harness(_workspace_config(tmp_path), model=_delegating_script())

    def boom(event: ProgressEvent) -> None:
        raise RuntimeError("回调炸了")

    outcome = await harness.run("写个文件", on_event=boom)

    assert outcome.final_output == "完成"


def test_format_event_shapes():
    assert format_event(ProgressEvent("agent_start", "supervisor")) == "> supervisor"
    assert format_event(ProgressEvent("agent_start", "coder", 1)) == "  > coder"

    tool_start = ProgressEvent(
        "tool_start", "coder", 1, tool="write_file", detail='{"path": "a.txt"}'
    )
    assert format_event(tool_start) == '  . write_file({"path": "a.txt"})'

    agent_end = ProgressEvent("agent_end", "coder", 1, detail="已写入")
    assert format_event(agent_end) == "  < coder: 已写入"


def test_preview_collapses_newlines_and_truncates():
    assert preview("a\n\n   b") == "a b"
    assert preview(None) == ""
    assert len(preview("x" * 500)) < 200


def test_console_reporter_writes_to_the_given_stream():
    buffer = io.StringIO()

    ConsoleReporter(buffer)(ProgressEvent("agent_start", "supervisor"))

    assert buffer.getvalue() == "> supervisor\n"
