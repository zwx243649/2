"""把 runs/ 目录读成前端能直接用的结构。

这一层是纯数据，不碰 HTTP，所以可以单独测试。
"""

from __future__ import annotations

import json
import re
import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .usage import summarize_usage

# run_id 形如 20261001-144004 或 20261001-144004-1（同一秒内多次运行）
RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}(-\d+)?$")

SUMMARY_FILENAME = "summary.json"

# 列表只需要这几个标量字段。完整 run.json 里 spans 占了九成以上，
# 为了列个表去解析它是纯浪费。
SUMMARY_KEYS = ("goal", "session_id", "last_agent", "duration_s", "model_calls", "usage")


def build_summary(data: dict[str, Any]) -> dict[str, Any]:
    """从完整运行记录里抽出列表需要的字段。

    写入方（runner）在落盘时顺手存一份，保证两边用的字段列表永远一致。
    """
    summary = {key: data.get(key) for key in SUMMARY_KEYS}
    # usage 必须在这里就算好再存。
    # 老记录的顶层 usage 可能是缺失的、或者是被字符串化的，
    # 那种情况下唯一的信息来源是 spans —— 而摘要里没有 spans。
    # 直接复制引用的话，摘要落盘的那一刻这个数字就永久丢了。
    summary["usage"] = _extract_usage(data)
    return summary


class RunNotFound(LookupError):
    """请求的 run 不存在，或 id 非法。"""


@dataclass
class RunSummary:
    run_id: str
    goal: str
    last_agent: str
    duration_s: float
    model_calls: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    total_tokens: int
    session_id: str | None = None

    @property
    def display_time(self) -> str:
        """20261001-144004 -> 10-01 14:40:04"""
        raw = self.run_id.split("-")
        if len(raw) < 2 or len(raw[0]) != 8:
            return self.run_id
        date, clock = raw[0], raw[1]
        return f"{date[4:6]}-{date[6:8]} {clock[:2]}:{clock[2:4]}:{clock[4:6]}"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "display_time": self.display_time}


@dataclass
class SessionInfo:
    """一次会话的汇总。不单独存，直接从 runs/ 分组推出来。"""

    session_id: str
    title: str
    run_count: int
    total_tokens: int
    first_run: str
    last_run: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    """只允许固定格式的目录名，防止路径穿越。"""
    if not RUN_ID_PATTERN.match(run_id or ""):
        raise RunNotFound(f"非法的 run id: {run_id!r}")
    target = (runs_dir / run_id).resolve()
    if not target.is_dir() or runs_dir.resolve() not in target.parents:
        raise RunNotFound(f"找不到运行记录: {run_id}")
    return target


def _read_payload(run_dir: Path) -> dict[str, Any]:
    payload = run_dir / "run.json"
    if not payload.is_file():
        raise RunNotFound(f"{run_dir.name} 里没有 run.json")
    return json.loads(payload.read_text(encoding="utf-8"))


def _read_summary(run_dir: Path) -> dict[str, Any]:
    """优先读 summary.json；老记录没有就退回解析完整的 run.json。"""
    small = run_dir / SUMMARY_FILENAME
    if small.is_file():
        try:
            data = json.loads(small.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass  # 坏了就当没有，退回完整记录，不影响读取
    return _read_payload(run_dir)


def _extract_usage(data: dict[str, Any]) -> dict[str, int]:
    """优先用写好的 usage；老记录没有就现算一遍。"""
    usage = _coerce_usage(data.get("usage"))
    if usage is None:
        usage = asdict(summarize_usage(_normalize_spans(data.get("spans") or [])))
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "reasoning_tokens": int(usage.get("reasoning_tokens", 0) or 0),
        "cached_tokens": int(usage.get("cached_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _coerce_usage(value: Any) -> dict[str, Any] | None:
    """把 usage 规整成 dict。

    追踪层早期版本用 str() 处理非数值字段，导致老记录里 usage 被存成了
    Python dict 的字符串形式："{'input_tokens': 865, ...}"。
    这里尽力解析回来，让历史运行也能参与对比。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError, MemoryError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _normalize_spans(spans: list[Any]) -> list[dict[str, Any]]:
    """把每个 span 里的 usage 也解析回 dict，否则汇总时会漏掉。"""
    out: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        usage = _coerce_usage(span.get("usage"))
        out.append({**span, "usage": usage} if usage is not None else span)
    return out


def summarize_run(run_id: str, data: dict[str, Any]) -> RunSummary:
    usage = _extract_usage(data)
    session_id = data.get("session_id")
    return RunSummary(
        run_id=run_id,
        goal=str(data.get("goal", "")),
        last_agent=str(data.get("last_agent", "")),
        duration_s=float(data.get("duration_s", 0.0) or 0.0),
        model_calls=int(data.get("model_calls", 0) or 0),
        session_id=str(session_id) if session_id else None,
        **usage,
    )


def list_runs(runs_dir: Path) -> list[RunSummary]:
    """最新的排在最前面。坏掉的目录直接跳过，不让它拖垮整个列表。"""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []

    summaries: list[RunSummary] = []
    for entry in runs_dir.iterdir():
        if not entry.is_dir() or not RUN_ID_PATTERN.match(entry.name):
            continue
        try:
            summaries.append(summarize_run(entry.name, _read_summary(entry)))
        except (RunNotFound, json.JSONDecodeError, OSError):
            continue

    summaries.sort(key=lambda item: item.run_id, reverse=True)
    return summaries


def list_sessions(runs_dir: Path) -> list[SessionInfo]:
    """按会话分组。没有 session_id 的运行（一次性任务）不计入。"""
    grouped: dict[str, list[RunSummary]] = {}
    for summary in list_runs(runs_dir):
        if summary.session_id:
            grouped.setdefault(summary.session_id, []).append(summary)

    sessions: list[tuple[str, SessionInfo]] = []
    for session_id, runs in grouped.items():
        ordered = sorted(runs, key=lambda item: item.run_id)  # 最早在前
        sessions.append(
            (
                ordered[-1].run_id,
                SessionInfo(
                    session_id=session_id,
                    title=ordered[0].goal,
                    run_count=len(ordered),
                    total_tokens=sum(run.total_tokens for run in ordered),
                    first_run=ordered[0].display_time,
                    last_run=ordered[-1].display_time,
                ),
            )
        )

    sessions.sort(key=lambda item: item[0], reverse=True)  # 最近活跃的在前
    return [info for _, info in sessions]


def load_run(runs_dir: Path, run_id: str) -> dict[str, Any]:
    """返回单次运行的完整详情。"""
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    data = _read_payload(run_dir)

    summary = summarize_run(run_id, data)
    return {
        "summary": summary.as_dict(),
        "final_output": str(data.get("final_output", "")),
        "transcript": data.get("transcript") or [],
        "spans": data.get("spans") or [],
    }


__all__ = [
    "RUN_ID_PATTERN",
    "SUMMARY_FILENAME",
    "RunNotFound",
    "RunSummary",
    "SessionInfo",
    "build_summary",
    "list_runs",
    "list_sessions",
    "load_run",
    "summarize_run",
]
