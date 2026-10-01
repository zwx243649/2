"""进程内的后台任务。

网页上发起的操作（批准 / 续跑）以前是同步 POST —— 请求会一直挂到运行结束，
既没有"正在跑"这个状态，也没有可以叫停的对象。改成后台线程之后，
请求立刻返回，页面上有东西可看、也有东西可停。

同一时刻只允许一个任务：Harness 的追踪开关是进程级全局状态，
并发跑两个会互相覆盖。这不是偷懒，是真的不能并行。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .cancel import CancelToken


@dataclass
class BackgroundTask:
    key: str  # 关联的 run_id
    label: str
    started_at: float
    cancel_token: CancelToken
    finished: bool = False
    outcome: Any = None
    error: str | None = None

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.started_at

    @property
    def cancelling(self) -> bool:
        return self.cancel_token.cancelled and not self.finished

    @property
    def outcome_run_id(self) -> str | None:
        return getattr(self.outcome, "run_id", None)

    @property
    def outcome_status(self) -> str | None:
        return getattr(self.outcome, "status", None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "elapsed_s": round(self.elapsed_s, 1),
            "finished": self.finished,
            "cancelling": self.cancelling,
            "error": self.error,
            "outcome_run_id": self.outcome_run_id,
            "outcome_status": self.outcome_status,
        }


class TaskRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: BackgroundTask | None = None

    def get(self) -> BackgroundTask | None:
        with self._lock:
            return self._current

    def is_busy(self) -> bool:
        with self._lock:
            return self._current is not None and not self._current.finished

    def start(
        self,
        key: str,
        label: str,
        fn: Callable[[CancelToken], Any],
    ) -> BackgroundTask:
        with self._lock:
            if self._current is not None and not self._current.finished:
                raise RuntimeError("已经有任务在跑，先等它结束或把它停掉")
            task = BackgroundTask(
                key=key,
                label=label,
                started_at=time.time(),
                cancel_token=CancelToken(),
            )
            self._current = task

        def run() -> None:
            try:
                task.outcome = fn(task.cancel_token)
            except Exception as exc:  # 后台线程里出错不能把服务带崩
                task.error = f"{type(exc).__name__}: {exc}"
            finally:
                task.finished = True

        threading.Thread(
            target=run, daemon=True, name=f"harness-task-{key}"
        ).start()
        return task

    def cancel(self, key: str) -> bool:
        with self._lock:
            task = self._current
            if task is None or task.finished or task.key != key:
                return False
            task.cancel_token.cancel()
            return True

    def cancel_current(self) -> bool:
        """停掉当前任务。新任务还没有 run_id，所以不能按 key 找。"""
        with self._lock:
            task = self._current
            if task is None or task.finished:
                return False
            task.cancel_token.cancel()
            return True

    def clear(self) -> None:
        """仅供测试使用。"""
        with self._lock:
            self._current = None


__all__ = ["BackgroundTask", "TaskRegistry"]
