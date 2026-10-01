"""Supervisor + worker 多智能体 harness。"""

from __future__ import annotations

from typing import Any

from .config import HarnessConfig

__all__ = ["Harness", "HarnessConfig", "RunOutcome", "__version__"]

__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    """按需导入 Harness / RunOutcome。

    它们在 runner 里，而 runner 会拉起整个 agents SDK（实测 6 秒）。
    如果在这里顶层导入，那么 `import harness` —— 包括 --help / --pending
    这些根本用不到模型的命令 —— 全都要先等 SDK 加载完。

    这样写之后 `from harness import Harness` 依然照常工作，只是发生在真正
    用到它的时候。
    """
    if name in ("Harness", "RunOutcome"):
        from . import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
