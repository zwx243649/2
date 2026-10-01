"""本地追踪处理器。

supervisor 只能看到 worker 的最终结论（这是 context 隔离的代价），
但工程上我们必须能看到 worker 内部发生了什么。
这里用 TracingProcessor 把 span 全部收在本地，既保留可观测性，又不上传任何数据。
"""

from __future__ import annotations

from typing import Any

from agents import TracingProcessor

MAX_FIELD_CHARS = 800


def _clip(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """截断超长文本，但保留 dict/list 的结构。

    早期版本对任何非数值都做 str()，结果把 usage 这类结构化字段压成了字符串，
    下游没法再统计 token。
    """
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _clip(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(item, limit) for item in value]
    text = str(value)
    return text if len(text) <= limit else text[:limit] + " …[截断]"


def _span_payload(span: Any) -> dict[str, Any]:
    data = getattr(span, "span_data", None)
    payload: dict[str, Any] = {
        "class": type(data).__name__ if data is not None else None,
        "type": getattr(data, "type", None),
    }
    for slot in getattr(type(data), "__slots__", ()):  # SpanData 用 __slots__
        payload[slot] = _clip(getattr(data, slot, None))

    error = getattr(span, "error", None)
    if error is not None:
        payload["error"] = _clip(getattr(error, "message", error))
    return payload


class LocalTraceProcessor(TracingProcessor):
    """把 trace / span 收集到内存，供运行产物和调试使用。"""

    def __init__(self) -> None:
        self.traces: list[dict[str, Any]] = []
        self.spans: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.traces.clear()
        self.spans.clear()

    def on_trace_start(self, trace: Any) -> None:
        self.traces.append(
            {
                "event": "start",
                "trace_id": getattr(trace, "trace_id", None),
                "workflow_name": getattr(trace, "name", None),
                "started_at": _clip(getattr(trace, "started_at", None)),
            }
        )

    def on_trace_end(self, trace: Any) -> None:
        self.traces.append(
            {
                "event": "end",
                "trace_id": getattr(trace, "trace_id", None),
                "workflow_name": getattr(trace, "name", None),
                "ended_at": _clip(getattr(trace, "ended_at", None)),
            }
        )

    def on_span_start(self, span: Any) -> None:
        return None

    def on_span_end(self, span: Any) -> None:
        self.spans.append(
            {
                "span_id": getattr(span, "span_id", None),
                "parent_id": getattr(span, "parent_id", None),
                "started_at": _clip(getattr(span, "started_at", None)),
                "ended_at": _clip(getattr(span, "ended_at", None)),
                **_span_payload(span),
            }
        )

    def shutdown(self) -> None:
        return None

    def force_flush(self) -> None:
        return None

    # ---- 便于人工阅读 ----

    def format_timeline(self) -> str:
        lines: list[str] = []
        for index, span in enumerate(self.spans, start=1):
            kind = span.get("type") or span.get("class") or "?"
            name = span.get("name") or ""
            extra = ""
            if kind == "function":
                extra = f" -> {_clip(span.get('output'), 200)}"
            elif kind == "generation":
                extra = f" [{span.get('model')}]"
            lines.append(f"{index:>3}. {kind:<12} {name}{extra}")
            error = span.get("error")
            if error:
                lines.append(f"     !! {error}")
        return "\n".join(lines) if lines else "（没有采集到 span）"


__all__ = ["LocalTraceProcessor"]
