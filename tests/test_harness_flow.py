from __future__ import annotations

import json

from harness import Harness, HarnessConfig
from harness.testing import ScriptedModel, text_response, tool_call_response


def make_config(tmp_path, **overrides):
    defaults = {
        "workspace": tmp_path / "workspace",
        "runs_dir": tmp_path / "runs",
        "tracing": "local",
    }
    defaults.update(overrides)
    return HarnessConfig(**defaults)


async def test_supervisor_delegates_and_synthesizes(tmp_path):
    model = ScriptedModel(
        [
            tool_call_response("researcher", {"input": "看看工作区里有什么"}, call_id="c1"),
            text_response("工作区是空的。", response_id="r1"),
            text_response("结论：工作区为空，可以从零开始。", response_id="r2"),
        ]
    )
    harness = Harness(make_config(tmp_path), model=model)

    outcome = await harness.run("看看工作区里有什么")

    assert "结论" in outcome.final_output
    assert outcome.last_agent == "supervisor"

    kinds = [entry["kind"] for entry in outcome.transcript]
    assert "ToolCallItem" in kinds
    assert "ToolCallOutputItem" in kinds

    delegation = next(e for e in outcome.transcript if e["kind"] == "ToolCallItem")
    assert delegation["tool"] == "researcher"

    handback = next(e for e in outcome.transcript if e["kind"] == "ToolCallOutputItem")
    assert "工作区是空的" in handback["output"]

    # 最后一条助手消息的文本必须真的被解析出来（曾经因为读错字段变成空串）
    messages = [e for e in outcome.transcript if e["kind"] == "MessageOutputItem"]
    assert messages and messages[-1]["text"].strip()
    assert "结论" in messages[-1]["text"]

    # 两次 supervisor 调用 + 一次 worker 调用 = 3 次 generation span
    assert outcome.model_calls == 3
    # usage 会被汇总进 RunOutcome（每次调用 100 输入 + 20 输出）
    assert outcome.usage.input_tokens == 300
    assert outcome.usage.output_tokens == 60
    assert outcome.usage.total_tokens == 360

    tool_lists = [call["tools"] for call in model.calls]
    # supervisor 看到的是成员名单
    assert tool_lists[0] == ["coder", "researcher", "reviewer"]
    # researcher 只拿到只读工具，拿不到 write_file —— 权限边界确实生效
    assert ["list_files", "read_file"] in tool_lists


async def test_worker_writes_a_real_file_through_the_tool(tmp_path):
    model = ScriptedModel(
        [
            tool_call_response(
                "coder",
                {"input": "把 hello 写进 out.txt"},
                call_id="c1",
            ),
            tool_call_response(
                "write_file",
                {"path": "out.txt", "content": "hello"},
                call_id="c2",
            ),
            text_response("已写入 out.txt", response_id="r1"),
            text_response("完成：产出 out.txt", response_id="r2"),
        ]
    )
    harness = Harness(make_config(tmp_path), model=model)

    outcome = await harness.run("创建 out.txt")

    assert (tmp_path / "workspace" / "out.txt").read_text(encoding="utf-8") == "hello"
    assert "out.txt" in outcome.final_output
    assert outcome.model_calls == 4

    # supervisor 只能看到 worker 的最终结论，看不到 worker 内部的 write_file 调用
    supervisor_tools = [call["tools"] for call in model.calls]
    assert supervisor_tools[0] == ["coder", "researcher", "reviewer"]
    assert supervisor_tools[1] == ["list_files", "read_file", "write_file"]

    span_names = [span.get("name") for span in outcome.spans]
    assert "coder" in span_names
    assert "supervisor" in span_names


async def test_artifacts_are_written(tmp_path):
    model = ScriptedModel([text_response("直接回答，没有委派。")])
    harness = Harness(make_config(tmp_path), model=model)

    outcome = await harness.run("回答一个问题")

    assert outcome.run_dir is not None
    assert outcome.run_dir.is_dir()

    payload = json.loads((outcome.run_dir / "run.json").read_text(encoding="utf-8"))
    assert payload["goal"] == "回答一个问题"
    assert payload["final_output"] == "直接回答，没有委派。"
    assert (outcome.run_dir / "final.md").exists()
    assert (outcome.run_dir / "timeline.txt").exists()


async def test_run_writes_a_small_summary_alongside_the_full_record(tmp_path):
    """列表接口靠这份小文件，不必解析完整记录。"""
    model = ScriptedModel([text_response("ok")])
    harness = Harness(make_config(tmp_path), model=model)

    outcome = await harness.run("写摘要")

    full = outcome.run_dir / "run.json"
    small = outcome.run_dir / "summary.json"
    assert small.is_file()
    # 这正是优化点：完整记录比摘要大一个数量级
    assert full.stat().st_size > small.stat().st_size * 5
    # 完整记录里有 spans，摘要里不该有
    payload = json.loads(small.read_text(encoding="utf-8"))
    assert "spans" not in payload
    assert "transcript" not in payload
    assert payload["goal"] == "写摘要"


async def test_shell_tool_is_absent_until_enabled(tmp_path):
    model = ScriptedModel([text_response("ok")])
    harness = Harness(make_config(tmp_path), model=model)
    coder = next(w for w in harness.workers if w.name == "coder")

    assert "run_command" not in {tool.name for tool in coder.tools}

    enabled = Harness(make_config(tmp_path, allow_shell=True), model=model)
    coder_enabled = next(w for w in enabled.workers if w.name == "coder")

    assert "run_command" in {tool.name for tool in coder_enabled.tools}


async def test_empty_goal_is_rejected(tmp_path):
    harness = Harness(make_config(tmp_path), model=ScriptedModel([]))

    try:
        await harness.run("   ")
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("空 goal 应该报错")
