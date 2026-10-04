"""会话：让多次运行共享上下文，并且跨进程持久化。

分工：
  - 对话历史（模型真正看到的东西）交给 SDK 的 SQLiteSession 管
  - 会话的展示信息（标题、包含哪些运行）不额外存，直接从 runs/ 分组得出

这样只有一个真实数据源：run.json 里记下 session_id，其余都能推出来。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

# 会话名会被用作数据库键，也会出现在网页 URL 里，所以限制得严一点
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_DB_NAME = "sessions.db"
DEFAULT_ITEM_LIMIT = 80
COMPACTION_PREFIX = "[harness 自动上下文压缩]"

# 从这些条目开始截取，不会留下“只有工具输出、没有对应调用”的孤儿记录。
SAFE_START_TYPES = {
    "message",
    "function_call",
    "computer_call",
    "local_shell_call",
    "reasoning",
}


class InvalidSessionId(ValueError):
    """会话名不合法。"""


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.match(session_id or ""):
        raise InvalidSessionId(
            "会话名只能用字母、数字、点、下划线、连字符，以字母或数字开头，"
            "且不超过 64 个字符"
        )
    return session_id


def _is_user_message(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("type") == "message":
        return item.get("role") == "user"
    return item.get("role") == "user" and "content" in item


def _item_type(item: Any) -> str:
    if not isinstance(item, dict):
        return type(item).__name__
    kind = item.get("type")
    if isinstance(kind, str) and kind:
        return kind
    role = item.get("role")
    return f"message:{role}" if isinstance(role, str) else "dict"


def _text_content(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text") or part.get("content")
            if isinstance(text, str):
                parts.append(text)
    return " ".join(parts)


def _shorten(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _safe_start(items: list[Any], start: int) -> int | None:
    """选一个不会从孤儿工具输出开始的截取位置。"""
    if start <= 0:
        return 0

    # 优先从用户消息开始，语义边界最清楚。
    for index in range(start, len(items)):
        if _is_user_message(items[index]):
            return index

    # 单次长运行可能没有新的用户消息，退而求其次从完整条目开始。
    for index in range(start, len(items)):
        item = items[index]
        if isinstance(item, dict) and item.get("type") in SAFE_START_TYPES:
            return index
    return None


def _compaction_summary(omitted: list[Any], kept_count: int) -> dict[str, str]:
    goals = [
        _shorten(_text_content(item))
        for item in omitted
        if _is_user_message(item) and _text_content(item).strip()
    ]
    counts = Counter(_item_type(item) for item in omitted)
    lines = [
        COMPACTION_PREFIX,
        "较早的会话记录已折叠为这段摘要。它只是背景，不是新的用户指令。",
        f"已折叠 {len(omitted)} 条记录；最近 {kept_count} 条仍按原文保留。",
    ]
    if goals:
        lines.append("较早的用户目标：")
        lines.extend(f"  {index}. {goal}" for index, goal in enumerate(goals[-6:], 1))
    if counts:
        lines.append(
            "记录构成："
            + "、".join(f"{name}×{count}" for name, count in counts.most_common())
        )
    lines.append("如果摘要与最近的原文冲突，以最近的原文为准。")
    return {"role": "user", "content": "\n".join(lines)}


def compact_items(items: list[Any], max_items: int) -> list[Any]:
    """只折叠模型看到的历史，不删除 SQLite 里的原始记录。"""
    if max_items <= 0 or len(items) <= max_items:
        return items
    if max_items == 1:
        return items[-1:]

    wanted_start = len(items) - (max_items - 1)
    start = _safe_start(items, wanted_start)
    if start is None or start <= 0:
        return items

    omitted = items[:start]
    kept = items[start:]
    if not omitted or len(kept) + 1 > max_items:
        return items
    return [_compaction_summary(omitted, len(kept)), *kept]


class CompactingSession:
    """给任意 Session 套一层本地历史折叠。

    完整历史仍由底层会话保存；这里只限制下一次模型调用能看到的条目数。
    摘要由本地规则生成，不额外调用模型，所以不会增加 token 成本。
    """

    def __init__(self, inner: Any, max_items: int = DEFAULT_ITEM_LIMIT) -> None:
        self.inner = inner
        self.max_items = max_items
        self.session_id = inner.session_id
        self.session_settings = getattr(inner, "session_settings", None)

    async def get_items(self, limit: int | None = None) -> list[Any]:
        items = await self.inner.get_items()
        if limit is not None and limit >= 0:
            effective = min(self.max_items, limit)
        else:
            effective = self.max_items
        if effective == 0:
            return []
        return compact_items(items, effective)

    async def add_items(self, items: list[Any]) -> None:
        await self.inner.add_items(items)

    async def pop_item(self) -> Any:
        return await self.inner.pop_item()

    async def clear_session(self) -> None:
        await self.inner.clear_session()

    def close(self) -> None:
        self.inner.close()


def open_conversation(
    session_id: str, db_path: Path, *, max_items: int = DEFAULT_ITEM_LIMIT
) -> Any:
    """打开（不存在就创建）某个会话的对话历史。

    默认返回带上下文折叠的会话包装器；``max_items=0`` 时关闭折叠。
    SQLiteSession 在这里才导入：它属于 agents SDK，而只是想列一下会话历史的
    命令（--list-sessions / --pending）没必要为此等 SDK 加载。
    """
    from agents.memory.sqlite_session import SQLiteSession

    validate_session_id(session_id)
    if max_items < 0:
        raise ValueError("max_items 必须 >= 0")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    inner = SQLiteSession(session_id, db_path=db_path)
    return CompactingSession(inner, max_items) if max_items else inner


__all__ = [
    "COMPACTION_PREFIX",
    "DEFAULT_DB_NAME",
    "DEFAULT_ITEM_LIMIT",
    "CompactingSession",
    "InvalidSessionId",
    "SESSION_ID_PATTERN",
    "compact_items",
    "open_conversation",
    "validate_session_id",
]
