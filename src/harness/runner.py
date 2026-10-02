"""编排入口：把 agent、工具、追踪组装成一次可执行、可留档的运行。"""

from __future__ import annotations

import asyncio
import contextlib
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
    RunState,
    Runner,
    add_trace_processor,
    set_trace_processors,
    set_tracing_disabled,
)

from .agents import apply_strict_policy, build_supervisor, build_workers
from .cancel import CancelToken
from .config import HarnessConfig
from .progress import Emitter, ProgressHooks
from .provider import build_model, build_model_settings
from .runs_index import SUMMARY_FILENAME, build_summary, previous_test_result
from .sessions import open_conversation
from .testresults import ResultTracker
from .tools import build_read_tools, build_shell_tools, build_write_tools
from .tracing import LocalTraceProcessor
from .usage import TokenUsage, summarize_usage
from .workspace import Workspace

WORKFLOW_NAME = "multi-agent-harness"
STATE_FILENAME = "state.json"

# 这几项决定一次运行长什么样。续跑时必须一致：
#   - allow_shell 不一致 → 待执行的工具在新建的图里不存在（实测踩过，会永远卡住）
#   - max_turns 不一致   → 续跑可能被静默截断，比报错更难排查
GRAPH_CONFIG_KEYS = (
    "model",
    "allow_shell",
    "approve_shell",
    "strict_tools",
    "max_turns",
    "worker_max_turns",
)


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


def describe_interruptions(interruptions: list[Any]) -> list[dict[str, Any]]:
    """把待批准的工具调用转成可读、可序列化的形式。"""
    pending: list[dict[str, Any]] = []
    for item in interruptions:
        raw = getattr(item, "raw_item", None)
        pending.append(
            {
                "tool": getattr(item, "tool_name", None)
                or getattr(raw, "name", "")
                or "?",
                "arguments": getattr(raw, "arguments", "") or "",
            }
        )
    return pending


def resume_turn_budget(state_payload: dict[str, Any], base: int) -> int:
    """续跑时该写进 state 的 max_turns。

    SDK 从 RunState 恢复时用的是 **state 里存的** max_turns（run.py 里
    `max_turns = run_state._max_turns`），传给 Runner 的参数会被忽略。
    而 current_turn 也是恢复过来的 —— 两者一起沿用，累计到上限之后这个
    任务就永远续不动了，报 MaxTurnsExceeded，还看不出是这么回事。

    所以每次续跑都给它一份新预算：base + 已经用掉的回合数。
    """
    try:
        used = int(state_payload.get("current_turn", 0) or 0)
    except (TypeError, ValueError):
        used = 0
    return base + max(used, 0)


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
    run_id: str | None = None
    session_id: str | None = None
    status: str = "completed"  # completed | paused | cancelled
    pending: list[dict[str, Any]] = field(default_factory=list)
    resumed_from: str | None = None
    stop_reason: str | None = None

    @property
    def model_calls(self) -> int:
        return self.usage.calls

    @property
    def usage(self) -> TokenUsage:
        return summarize_usage(self.spans)

    def render(self, *, verbose: bool = False) -> str:
        if self.status == "cancelled":
            return "\n".join(
                [
                    "=" * 60,
                    f"目标\n{self.goal}",
                    "-" * 60,
                    f"⏹ 已停止（{self.stop_reason or '用户手动停止'}）",
                    "",
                    "状态已经存下来了，可以接着跑：",
                    f"  python -m harness --resume {self.run_id or '(见运行目录)'}",
                    "-" * 60,
                    f"消耗: {self.usage.render()}",
                    f"运行产物: {self.run_dir}",
                    "=" * 60,
                ]
            )

        if self.status == "paused":
            head = [
                "=" * 60,
                f"目标\n{self.goal}",
                "-" * 60,
                "⏸ 已暂停：有工具调用在等待你批准",
                "",
            ]
            for item in self.pending:
                head.append(f"  [{item['tool']}] {item['arguments']}")
            head += [
                "",
                f"批准：python -m harness --approve {self.run_id or '(见运行目录)'}",
                f"拒绝：python -m harness --reject {self.run_id or '(见运行目录)'}",
            ]
            if self.run_dir is not None:
                head.append(f"运行产物: {self.run_dir}")
            head.append("=" * 60)
            return "\n".join(head)

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

    def __init__(
        self,
        config: HarnessConfig,
        model: Any = None,
        previous_test_result: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.processor = LocalTraceProcessor()
        self.progress = ProgressHooks()
        # 盯着测试结果有没有变差：跨 resume 的记忆靠这个 tracker
        # 连续变差时由 tracker 回调 _request_stop 主动叫停
        self._active_cancel: CancelToken | None = None
        self.test_results = ResultTracker(
            previous_test_result, on_stop=self._request_stop
        )
        self._conversations: dict[str, Any] = {}
        self._configure_tracing()

        self.workspace = Workspace(config.workspace)
        self.model = model if model is not None else build_model(config)

        read_tools = build_read_tools(self.workspace, strict=config.strict_tools)
        write_tools = build_write_tools(self.workspace, strict=config.strict_tools)
        shell_tools = (
            build_shell_tools(config, self.workspace, self.test_results)
            if config.allow_shell
            else []
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
        cancel_token: CancelToken | None = None,
    ) -> RunOutcome:
        """跑一次任务。

        - ``on_event``：实时进度回调
        - ``session_id``：带上它就能复用同名会话的历史，实现多轮追问
        - ``cancel_token``：发出取消信号后本轮会干净收尾，并把状态存下来供续跑
        """
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal 不能为空")

        session = self._conversation(session_id) if session_id else None
        self.processor.reset()
        started = time.perf_counter()

        result, cancelled = await self._execute(
            goal, session=session, cancel_token=cancel_token, on_event=on_event
        )

        outcome = self._build_outcome(
            goal,
            result,
            cancelled,
            time.perf_counter() - started,
            session_id=session_id,
        )
        return self._finish(outcome, result)

    def run_sync(
        self,
        goal: str,
        *,
        session_id: str | None = None,
        on_event: Emitter | None = None,
        cancel_token: CancelToken | None = None,
    ) -> RunOutcome:
        return asyncio.run(
            self.run(
                goal,
                session_id=session_id,
                on_event=on_event,
                cancel_token=cancel_token,
            )
        )

    def resume_sync(
        self,
        run_id: str,
        *,
        approve: bool = True,
        on_event: Emitter | None = None,
        cancel_token: CancelToken | None = None,
    ) -> RunOutcome:
        return asyncio.run(
            self.resume(
                run_id,
                approve=approve,
                on_event=on_event,
                cancel_token=cancel_token,
            )
        )

    async def resume(
        self,
        run_id: str,
        *,
        approve: bool = True,
        on_event: Emitter | None = None,
        cancel_token: CancelToken | None = None,
    ) -> RunOutcome:
        """从暂停或被停止的运行继续。

        approve=True 放行待批准的调用，False 则拒绝；被停止的运行没有待批准项，
        两个值都只是继续往下跑。
        """
        run_dir = self.config.runs_dir / run_id
        state_path = run_dir / STATE_FILENAME
        if not state_path.is_file():
            raise FileNotFoundError(f"{run_id} 没有可继续的状态（找不到 state.json）")

        original = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self._check_graph_config(original)

        # 把上一次的测试结果捞回来，否则这一轮不知道「之前是多少」，
        # 也就判断不出有没有变差。
        previous = previous_test_result(self.config.runs_dir, run_id)
        if previous is not None:
            self.test_results.previous = previous.result
            self.test_results.latest = previous.result
            self.test_results.previous_command = previous.command
            self.test_results.latest_command = previous.command
            # 连续退步的计数也要接着数 —— 每次 resume 都是新的 Harness，
            # 不接着数的话永远攒不到叫停的阈值。
            self.test_results.consecutive_regressions = previous.regression_streak

        state_text = state_path.read_text(encoding="utf-8")
        state_payload = json.loads(state_text)
        state_payload["max_turns"] = resume_turn_budget(
            state_payload, self.config.max_turns
        )
        state = await RunState.from_json(self.supervisor, state_payload)

        for item in state.get_interruptions():
            if approve:
                state.approve(item)
            else:
                state.reject(item)

        self.processor.reset()
        started = time.perf_counter()
        result, cancelled = await self._execute(
            state,
            session=None,
            cancel_token=cancel_token,
            on_event=on_event,
        )

        # 续跑成功后才清掉待处理标记；失败的话状态还在，可以重试
        state_path.unlink(missing_ok=True)

        outcome = self._build_outcome(
            str(original.get("goal", "")),
            result,
            cancelled,
            time.perf_counter() - started,
            session_id=original.get("session_id"),
            resumed_from=run_id,
        )
        return self._finish(outcome, result)

    async def _execute(
        self,
        agent_input: Any,
        *,
        session: Any,
        cancel_token: CancelToken | None,
        on_event: Emitter | None,
    ) -> tuple[RunResult, bool]:
        """跑一轮，返回 (结果, 是否被取消)。

        用 run_streamed 而不是 run：只有它能在中途取消，同步的 run 没有任何
        中断入口。取消是协作式的 —— 轮询到信号后调 cancel()，运行会自己收尾，
        状态留在 result 里，之后可以续跑。
        """
        # 没传 token 也造一个：harness 自己（比如收敛检测）要靠它叫停
        token = cancel_token if cancel_token is not None else CancelToken()
        self._active_cancel = token
        self.progress.set_emitter(on_event)
        try:
            result = Runner.run_streamed(
                self.supervisor,
                agent_input,
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
            cancelled = False
            async for _event in result.stream_events():
                if not cancelled and token.cancelled:
                    cancelled = True
                    result.cancel()
            return result, cancelled
        finally:
            self._active_cancel = None
            self.progress.set_emitter(None)

    def _request_stop(self) -> None:
        """收敛检测判定「再改下去只会更糟」时走这里主动叫停。"""
        token = self._active_cancel
        if token is not None:
            token.cancel()

    def _build_outcome(
        self,
        goal: str,
        result: RunResult,
        cancelled: bool,
        duration: float,
        *,
        session_id: str | None = None,
        resumed_from: str | None = None,
    ) -> RunOutcome:
        interruptions = list(result.interruptions)
        if interruptions:
            status = "paused"
        elif cancelled:
            status = "cancelled"
        else:
            status = "completed"

        return RunOutcome(
            goal=goal,
            final_output="" if status != "completed" else str(result.final_output),
            last_agent=result.last_agent.name,
            duration_s=duration,
            transcript=serialize_items(result),
            spans=list(self.processor.spans),
            timeline=self.processor.format_timeline(),
            session_id=session_id,
            status=status,
            pending=describe_interruptions(interruptions),
            resumed_from=resumed_from,
            stop_reason=self.test_results.stop_reason if cancelled else None,
        )

    def _finish(self, outcome: RunOutcome, result: RunResult) -> RunOutcome:
        if self.config.save_artifacts:
            outcome.run_dir = self._persist(outcome, result)
            outcome.run_id = outcome.run_dir.name
        return outcome

    def _check_graph_config(self, original: dict[str, Any]) -> None:
        stored = original.get("graph_config")
        if not isinstance(stored, dict):
            return
        current = self._graph_config()
        diff = {
            key: {"原运行": stored.get(key), "当前": current.get(key)}
            for key in GRAPH_CONFIG_KEYS
            if key in stored and stored.get(key) != current.get(key)
        }
        if diff:
            raise ValueError(f"续跑需要和原运行相同的工具配置，但不一致：{diff}")

    def _conversation(self, session_id: str) -> Any:
        """同一个会话只打开一次，避免重复建连接。"""
        session = self._conversations.get(session_id)
        if session is None:
            session = open_conversation(session_id, self.config.sessions_db)
            self._conversations[session_id] = session
        return session

    def _graph_config(self) -> dict[str, Any]:
        """决定 agent 图形态的那几项配置。"""
        return {key: getattr(self.config, key) for key in GRAPH_CONFIG_KEYS}

    def close(self) -> None:
        """关闭所有会话连接。

        每个 SQLiteSession 持有连接和一把文件锁，不关就会留下 -wal / -shm；
        CLI 跑完进程退出无所谓，但长驻进程（比如以后的网页控制台）必须调用。
        """
        for session in self._conversations.values():
            with contextlib.suppress(Exception):  # 关闭失败不该影响主流程
                session.close()
        self._conversations.clear()

    def __enter__(self) -> Harness:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- 产物 ----

    def _persist(self, outcome: RunOutcome, result: RunResult) -> Path:
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
            "status": outcome.status,
            "pending": outcome.pending,
            "resumed_from": outcome.resumed_from,
            "graph_config": self._graph_config(),
            "test_result": self.test_results.latest,
            "test_command": self.test_results.latest_command,
            "regression_streak": self.test_results.consecutive_regressions,
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
        if outcome.status in ("paused", "cancelled"):
            # 完整运行状态：暂停时用来批准后继续，被停止时用来续跑
            (run_dir / STATE_FILENAME).write_text(
                result.to_state().to_string(),
                encoding="utf-8",
                newline="\n",
            )
        return run_dir


__all__ = [
    "CancelToken",
    "Harness",
    "RunOutcome",
    "render_transcript",
    "serialize_items",
]
