"""编排入口：把 agent、工具、追踪组装成一次可执行、可留档的运行。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agents import (
    ItemHelpers,
    RunConfig,
    RunResult,
    Runner,
    add_trace_processor,
    set_trace_processors,
    set_tracing_disabled,
)

from .agents import apply_strict_policy, build_supervisor, build_workers
from .config import HarnessConfig
from .progress import Emitter, ProgressHooks
from .provider import build_model, build_model_settings
from .runs_index import SUMMARY_FILENAME, build_summary
from .sessions import open_conversation
from .tools import build_read_tools, build_shell_tools, build_write_tools
from .tracing import LocalTraceProcessor
from .usage import TokenUsage, summarize_usage
from .workspace import Workspace

WORKFLOW_NAME = "multi-agent-harness"


def _clip(value: Any, limit: int = 600) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + " …[截断]"


def _message_text(item: Any) -> str:
    """MessageOutputItem 的文本要从 raw_item.content 取，SDK 提供了现成的 helper。"""
    return ItemHelpers.text_message_output(item)


def serialize_items(result: RunResult) -> list[dict[str, Any]]:
    """把 SDK 的运行条目转成可序列化的记录。

    注意：worker 是作为 tool 被调用的，所以这里只能看到一次委派调用和它的回传结论，
    看不到 worker 内部的思考过程。worker 内部过程在 trace span 里。
    """
    entries: list[dict[str, Any]] = []
    for item in result.new_items:
        kind = type(item).__name__
        entry: dict[str, Any] = {"kind": kind}

        agent = getattr(item, "agent", None)
        if agent is not None:
            entry["agent"] = getattr(agent, "name", None)

        raw = getattr(item, "raw_item", None)
        if kind == "MessageOutputItem":
            entry["text"] = _message_text(item)
        elif kind == "ToolCallItem":
            entry["tool"] = getattr(raw, "name", None)
            entry["arguments"] = _clip(getattr(raw, "arguments", None))
        elif kind == "ToolCallOutputItem":
            entry["output"] = _clip(getattr(item, "output", None))
        elif kind in {"HandoffOutputItem", "HandoffCallItem"}:
            entry["from"] = getattr(getattr(item, "source_agent", None), "name", None)
            entry["to"] = getattr(getattr(item, "target_agent", None), "name", None)
        else:
            entry["detail"] = _clip(raw if raw is not None else item)

        entries.append(entry)
    return entries


def render_transcript(entries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        kind = entry.get("kind")
        agent = entry.get("agent") or "-"
        if kind == "ToolCallItem":
            body = f"委派 {entry.get('tool')}({entry.get('arguments')})"
        elif kind == "ToolCallOutputItem":
            body = f"{entry.get('tool') or 'worker'} 回传: {entry.get('output')}"
        elif kind == "MessageOutputItem":
            body = entry.get("text") or ""
        elif kind in {"HandoffOutputItem", "HandoffCallItem"}:
            body = f"{entry.get('from')} -> {entry.get('to')}"
        else:
            body = str(entry.get("detail") or "")
        lines.append(f"{index:>3}. [{agent}] {body}".rstrip())
    return "\n".join(lines)


@dataclass
class RunOutcome:
    goal: str
    final_output: str
    last_agent: str
    duration_s: float
    transcript: list[dict[str, Any]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    timeline: str = ""
    run_dir: Path | None = None
    session_id: str | None = None

    @property
    def model_calls(self) -> int:
        return self.usage.calls

    @property
    def usage(self) -> TokenUsage:
        return summarize_usage(self.spans)

    def render(self, *, verbose: bool = False) -> str:
        parts = [
            "=" * 60,
            f"目标\n{self.goal}",
            "-" * 60,
            f"结论（最后处理者: {self.last_agent}）\n{self.final_output}",
            "-" * 60,
            f"委派轨迹（{len(self.transcript)} 条，模型调用 {self.model_calls} 次，"
            f"耗时 {self.duration_s:.1f}s）",
            render_transcript(self.transcript),
            "-" * 60,
            f"消耗: {self.usage.render()}",
        ]
        if verbose:
            parts += ["-" * 60, "内部 span 时间线", self.timeline]
        if self.run_dir is not None:
            parts += ["-" * 60, f"运行产物: {self.run_dir}"]
        parts.append("=" * 60)
        return "\n".join(parts)


class Harness:
    """supervisor + worker 多智能体 harness。

    注意：追踪开关在 Agents SDK 里是进程级全局状态，同一个进程里只应存在一个 Harness。
    """

    def __init__(self, config: HarnessConfig, model: Any = None) -> None:
        self.config = config
        self.processor = LocalTraceProcessor()
        self.progress = ProgressHooks()
        self._conversations: dict[str, Any] = {}
        self._configure_tracing()

        self.workspace = Workspace(config.workspace)
        self.model = model if model is not None else build_model(config)

        read_tools = build_read_tools(self.workspace, strict=config.strict_tools)
        write_tools = build_write_tools(self.workspace, strict=config.strict_tools)
        shell_tools = (
            build_shell_tools(config, self.workspace) if config.allow_shell else []
        )

        model_settings = build_model_settings(config)
        self.workers = build_workers(
            self.model, read_tools, write_tools, shell_tools, model_settings
        )
        self.progress.delegation_tools = {worker.name for worker in self.workers}
        self.supervisor = build_supervisor(
            config, self.model, self.workers, model_settings, self.progress
        )

        # 必须在 as_tool() 之后统一覆盖，否则 worker 工具会带着 strict=True 发出去
        apply_strict_policy([self.supervisor, *self.workers], config.strict_tools)

    # ---- 追踪 ----

    def _configure_tracing(self) -> None:
        mode = self.config.tracing
        if mode == "off":
            set_tracing_disabled(True)
            return

        set_tracing_disabled(False)
        if mode == "openai":
            # 保留 SDK 默认导出器，额外挂上本地收集器（上传前会脱敏）。
            add_trace_processor(self.processor)
        else:
            # 默认：只留本机，不向任何地方发送。
            set_trace_processors([self.processor])

    # ---- 运行 ----

    async def run(
        self,
        goal: str,
        *,
        session_id: str | None = None,
        on_event: Emitter | None = None,
    ) -> RunOutcome:
        """跑一次任务。

        - ``on_event``：实时进度回调
        - ``session_id``：带上它就能复用同名会话的历史，实现多轮追问
        """
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal 不能为空")

        session = self._conversation(session_id) if session_id else None
        self.processor.reset()
        started = time.perf_counter()

        self.progress.set_emitter(on_event)
        try:
            result = await Runner.run(
                self.supervisor,
                goal,
                max_turns=self.config.max_turns,
                hooks=self.progress,
                session=session,
                run_config=RunConfig(
                    workflow_name=WORKFLOW_NAME,
                    # local 模式数据不出本机，保留完整内容便于调试；
                    # openai 模式要上传，先脱敏。
                    trace_include_sensitive_data=self.config.tracing != "openai",
                ),
            )
        finally:
            self.progress.set_emitter(None)

        duration = time.perf_counter() - started
        outcome = RunOutcome(
            goal=goal,
            final_output=str(result.final_output),
            last_agent=result.last_agent.name,
            duration_s=duration,
            transcript=serialize_items(result),
            spans=list(self.processor.spans),
            timeline=self.processor.format_timeline(),
            session_id=session_id,
        )

        if self.config.save_artifacts:
            outcome.run_dir = self._persist(outcome)
        return outcome

    def run_sync(
        self,
        goal: str,
        *,
        session_id: str | None = None,
        on_event: Emitter | None = None,
    ) -> RunOutcome:
        return asyncio.run(self.run(goal, session_id=session_id, on_event=on_event))

    def _conversation(self, session_id: str) -> Any:
        """同一个会话只打开一次，避免重复建连接。"""
        session = self._conversations.get(session_id)
        if session is None:
            session = open_conversation(session_id, self.config.sessions_db)
            self._conversations[session_id] = session
        return session

    def close(self) -> None:
        """关闭所有会话连接。

        每个 SQLiteSession 持有连接和一把文件锁，不关就会留下 -wal / -shm；
        CLI 跑完进程退出无所谓，但长驻进程（比如以后的网页控制台）必须调用。
        """
        for session in self._conversations.values():
            try:
                session.close()
            except Exception:  # 关闭失败不该影响主流程
                pass
        self._conversations.clear()

    def __enter__(self) -> Harness:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- 产物 ----

    def _persist(self, outcome: RunOutcome) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = self.config.runs_dir / stamp
        suffix = 1
        while run_dir.exists():
            run_dir = self.config.runs_dir / f"{stamp}-{suffix}"
            suffix += 1
        run_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "goal": outcome.goal,
            "session_id": outcome.session_id,
            "final_output": outcome.final_output,
            "last_agent": outcome.last_agent,
            "duration_s": round(outcome.duration_s, 3),
            "model_calls": outcome.model_calls,
            "usage": outcome.usage.__dict__,
            "transcript": outcome.transcript,
            "spans": outcome.spans,
        }
        (run_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        # 顺手存一份小的，列表接口就不必去解析上面那个大文件
        (run_dir / SUMMARY_FILENAME).write_text(
            json.dumps(build_summary(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        (run_dir / "final.md").write_text(
            f"# 目标\n\n{outcome.goal}\n\n# 结论\n\n{outcome.final_output}\n",
            encoding="utf-8",
            newline="\n",
        )
        (run_dir / "timeline.txt").write_text(
            outcome.timeline + "\n\n" + render_transcript(outcome.transcript) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return run_dir


__all__ = ["Harness", "RunOutcome", "render_transcript", "serialize_items"]
