"""控制台输出的小工具。"""

from __future__ import annotations

import contextlib
import sys


def force_utf8_stdout() -> None:
    """尽量把 stdout 设成 UTF-8。

    Windows 控制台默认是 GBK，中文输出会变乱码。重定向到文件或管道时
    `reconfigure` 可能不可用 —— 输出格式的问题不值得让程序挂掉，随它去。
    """
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


__all__ = ["force_utf8_stdout"]
