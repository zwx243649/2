"""会话：让多次运行共享上下文，并且跨进程持久化。

分工：
  - 对话历史（模型真正看到的东西）交给 SDK 的 SQLiteSession 管
  - 会话的展示信息（标题、包含哪些运行）不额外存，直接从 runs/ 分组得出

这样只有一个真实数据源：run.json 里记下 session_id，其余都能推出来。
"""

from __future__ import annotations

import re
from pathlib import Path

from agents.memory.sqlite_session import SQLiteSession

# 会话名会被用作数据库键，也会出现在网页 URL 里，所以限制得严一点
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_DB_NAME = "sessions.db"


class InvalidSessionId(ValueError):
    """会话名不合法。"""


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.match(session_id or ""):
        raise InvalidSessionId(
            "会话名只能用字母、数字、点、下划线、连字符，以字母或数字开头，"
            "且不超过 64 个字符"
        )
    return session_id


def open_conversation(session_id: str, db_path: Path) -> SQLiteSession:
    """打开（不存在就创建）某个会话的对话历史。"""
    validate_session_id(session_id)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteSession(session_id, db_path=db_path)


__all__ = [
    "DEFAULT_DB_NAME",
    "InvalidSessionId",
    "SESSION_ID_PATTERN",
    "open_conversation",
    "validate_session_id",
]
