"""取消信号。

刻意放在一个零依赖的模块里：runner / tasks / cli 都要用它，而 runner 会拉起
整个 agents SDK。如果它定义在 runner 里，只想读个运行历史的命令也会被迫等
SDK 加载 —— 实测多等 6 秒。
"""

from __future__ import annotations

import threading


class CancelToken:
    """跨线程的取消信号。

    CLI 的 Ctrl+C 处理函数在信号回调里调 cancel()，跑在事件循环里的轮询检查它
    —— 这样取消是协作式的，运行能干净收尾并把状态存下来，而不是被
    KeyboardInterrupt 直接撕掉。
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


__all__ = ["CancelToken"]
