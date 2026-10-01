"""从测试输出里认出结果，并盯着它有没有变差。

起因是一次真实事故：agent 连续 8 次编辑同一个文件，每次改完跑一次 pytest，
失败数从 2 一路涨到 13，而整个 harness 里没有任何东西发现「方向反了」。

人的做法是注意到「我已经改第三次了，而且更糟」。所以这里做的就是把这句话
变成工具返回值的一部分，直接喂回给模型 —— 而不是等人去看日志。

跨 resume 的记忆是重点：每次 resume 都是一次全新的运行，彼此不知道对方，
所以上一次的结果必须从运行记录链（resumed_from）里捞回来。
"""

from __future__ import annotations

import re
from typing import Any

# pytest 的汇总行长这样：
#   13 failed, 112 passed in 2.44s
#   151 passed in 18.18s
#   1 failed, 2 passed, 1 error in 0.5s
SUMMARY_LINE = re.compile(
    r"^.*\b\d+\s+(?:passed|failed|errors?)\b.*$", re.MULTILINE
)
COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?)")

FAILURE_KEYS = ("failed", "errors")


def parse_test_summary(text: str) -> dict[str, int] | None:
    """从输出里提取测试汇总。认不出来就返回 None。"""
    lines = [match.group(0) for match in SUMMARY_LINE.finditer(text or "")]
    if not lines:
        return None

    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for number, kind in COUNT.findall(lines[-1]):
        key = "errors" if kind.startswith("error") else kind
        counts[key] += int(number)

    if not any(counts.values()):
        return None
    counts["total"] = counts["passed"] + counts["failed"] + counts["errors"]
    return counts


def failure_count(result: dict[str, int] | None) -> int:
    if not result:
        return 0
    return sum(int(result.get(key, 0) or 0) for key in FAILURE_KEYS)


def describe(result: dict[str, int] | None) -> str:
    if not result:
        return "（还没有测试结果）"
    parts = [f"{result.get('passed', 0)} passed"]
    if result.get("failed"):
        parts.append(f"{result['failed']} failed")
    if result.get("errors"):
        parts.append(f"{result['errors']} error")
    return ", ".join(parts)


class ResultTracker:
    """记住上一次的测试结果，发现变差就给出提示。

    只在**同一条命令**之间比较。先跑 `pytest tests/test_logfmt.py`（20 passed）
    再跑 `pytest tests/`（全量），范围完全不同 —— 直接比失败数会误报「变差了」。
    宁可漏报也不要误报：假警报会让模型去追一个不存在的问题。
    """

    def __init__(
        self,
        previous: dict[str, Any] | None = None,
        previous_command: str | None = None,
    ) -> None:
        self.previous: dict[str, int] | None = previous
        self.previous_command: str | None = previous_command
        self.latest: dict[str, int] | None = previous
        self.latest_command: str | None = previous_command

    def observe(self, command: str, output: str) -> str:
        """看一段命令输出。返回要追加给模型的提示（没有变化就返回空串）。"""
        result = parse_test_summary(output)
        if result is None:
            return ""

        before = self.previous
        same_command = self.previous_command == command
        self.latest = result
        self.latest_command = command

        if before is None or not same_command:
            self.previous = result
            self.previous_command = command
            return ""
        self.previous = result

        now = failure_count(result)
        was = failure_count(before)
        if now > was:
            return (
                f"\n\n⚠ 失败数从 {was} 涨到 {now}（多了 {now - was} 个）。"
                "这次改动很可能引入了新的失败 —— 先别继续猜着改，"
                "回头看看刚才改了什么，或者停下来报告卡在哪。"
            )
        if now < was:
            return f"\n\n✓ 失败数从 {was} 降到 {now}，在收敛。"
        return ""


__all__ = [
    "ResultTracker",
    "describe",
    "failure_count",
    "parse_test_summary",
]
