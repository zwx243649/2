"""运行时进度：把 SDK 的生命周期回调变成可读的实时事件。

为什么用 RunHooks 而不是 run_streamed：
对 supervisor/worker 这种结构，「谁委派给谁、worker 在调什么工具」比逐字吐 token
有用得多；而且 RunHooks 能在现有的非流式路径上工作，不需要模型实现流式接口。

坑：as_tool() 创建的嵌套运行不会继承父级 hooks，必须把同一个实例显式传给每个
worker tool，否则只能看到委派这一层，看不到 worker 内部。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, TextIO

from agents import RunHooks

MAX_PREVIEW = 150


def preview(value: Any, limit: int = MAX_PREVIEW) -> str:
    """压成单行并截断，避免刷屏。"""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + " …"


@dataclass(frozen=True)
class ProgressEvent:
    kind: str  # agent_start | agent_end | tool_start | tool_end
    agent: str
    depth: int = 0
    tool: str | None = None
    detail: str = ""


Emitter = Callable[[ProgressEvent], None]


class ProgressHooks(RunHooks):
    """把 SDK 钩子转成扁平事件。

    一个实例同时交给 supervisor 的每个 worker tool 和 Runner.run。
    两次运行之间用 set_emitter 切换消费者，不需要重建 agent 图。
    """

    def __init__(self, delegation_tools: set[str] | None = None) -> None:
        self._emitter: Emitter | None = None
        self._depth = 0
        # 这些「工具」其实是 worker。它们的回传内容会和 worker 自己的
        # agent_end 重复，所以只保留委派时的入参，丢掉返回。
        self.delegation_tools: set[str] = delegation_tools or set()

    def set_emitter(self, emitter: Emitter | None) -> None:
        self._emitter = emitter
        self._depth = 0

    def _emit(self, event: ProgressEvent) -> None:
        if self._emitter is None:
            return
        try:
            self._emitter(event)
        except Exception:  # 进度输出绝不能影响主流程
            pass

    async def on_agent_start(self, context: Any, agent: Any) -> None:
        self._emit(ProgressEvent("agent_start", agent.name, self._depth))
        self._depth += 1

    async def on_agent_end(self, context: Any, agent: Any, output: Any) -> None:
        self._depth = max(0, self._depth - 1)
        self._emit(
            ProgressEvent("agent_end", agent.name, self._depth, detail=preview(output))
        )

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        arguments = getattr(context, "tool_arguments", "") or ""
        self._emit(
            ProgressEvent(
                "tool_start",
                agent.name,
                self._depth,
                tool=getattr(tool, "name", None),
                detail=preview(arguments),
            )
        )

    async def on_tool_end(
        self, context: Any, agent: Any, tool: Any, result: Any
    ) -> None:
        if getattr(tool, "name", None) in self.delegation_tools:
            return
        self._emit(
            ProgressEvent(
                "tool_end",
                agent.name,
                self._depth,
                tool=getattr(tool, "name", None),
                detail=preview(result),
            )
        )


def format_event(event: ProgressEvent) -> str:
    pad = "  " * event.depth
    if event.kind == "agent_start":
        return f"{pad}> {event.agent}"
    if event.kind == "agent_end":
        return f"{pad}< {event.agent}" + (f": {event.detail}" if event.detail else "")
    if event.kind == "tool_start":
        args = f"({event.detail})" if event.detail else ""
        return f"{pad}. {event.tool}{args}"
    if event.kind == "tool_end":
        detail = f" -> {event.detail}" if event.detail else ""
        return f"{pad}. {event.tool}{detail}"
    return f"{pad}? {event.kind}"


class ConsoleReporter:
    """把事件打到 stderr，stdout 留给最终报告，方便重定向。"""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr

    def __call__(self, event: ProgressEvent) -> None:
        self.stream.write(format_event(event) + "\n")
        self.stream.flush()


__all__ = [
    "ConsoleReporter",
    "ProgressEvent",
    "ProgressHooks",
    "format_event",
    "preview",
]
