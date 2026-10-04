"""本地运行控制台：把 runs/ 用网页展示并支持发起、停止、批准任务。

刻意只用标准库：这是一个本地查看器，不值得为它引入 Web 框架。
默认绑定 127.0.0.1 —— runs/ 里含完整的 prompt 和产出，不该暴露到网络上。
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import HarnessConfig
from .runs_index import (
    STATE_FILENAME,
    RunNotFound,
    discard_run,
    list_runs,
    list_sessions,
    load_graph_config,
    load_run,
)
from .tasks import TaskRegistry
from .sessions import InvalidSessionId, validate_session_id

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8765

ACTION_PATTERN = re.compile(r"^/api/runs/([^/]+)/(approve|reject|resume|discard)$")
ACTION_HEADER = "X-Harness-Action"


def _status_payload(config: HarnessConfig) -> dict[str, Any]:
    """给前端系统状态页用的安全配置快照，不包含 API key。"""
    runs = list_runs(config.runs_dir)
    sessions = list_sessions(config.runs_dir)
    pending = sum(1 for run in runs if run.status != "completed")
    endpoint = config.base_url.split("?", 1)[0] if config.base_url else "OpenAI Responses API"
    return {
        "service": "harness-console",
        "status": "ready",
        "model": config.model,
        "endpoint": endpoint,
        "tracing": config.tracing,
        "allow_shell": config.allow_shell,
        "max_turns": config.max_turns,
        "worker_max_turns": config.worker_max_turns,
        "session_item_limit": config.session_item_limit,
        "model_timeout": config.model_timeout,
        "model_max_retries": config.model_max_retries,
        "routing_mode": config.routing_mode,
        "fast_path_max_turns": config.fast_path_max_turns,
        "dedupe_tools": config.dedupe_tools,
        "tool_output_chars": config.tool_output_chars,
        "workspace": str(config.workspace),
        "runs_dir": str(config.runs_dir),
        "run_count": len(runs),
        "session_count": len(sessions),
        "pending_count": pending,
        "total_tokens": sum(run.total_tokens for run in runs),
        "latest_run": runs[0].display_time if runs else None,
    }


def _progress_note(note):
    """把进度事件转成一行文字，交给任务记下来。"""

    def emit(event) -> None:
        try:
            from .progress import format_event

            note(format_event(event).strip())
        except Exception:  # 记进度失败绝不能影响运行
            pass

    return emit


def _resume_run(
    config: HarnessConfig,
    run_id: str,
    approve: bool,
    cancel_token=None,
    on_event=None,
):
    """执行一次批准/拒绝。放在函数里是为了延迟导入 agents SDK ——
    只看历史的话根本不需要把它加载起来。"""
    from .runner import Harness

    stored = load_graph_config(config.runs_dir, run_id)
    resolved = config.with_overrides(**stored) if stored else config

    harness = Harness(resolved)
    try:
        return harness.resume_sync(
            run_id,
            approve=approve,
            cancel_token=cancel_token,
            on_event=on_event,
        )
    finally:
        harness.close()


def _validate_resumable(config: HarnessConfig, run_id: str) -> None:
    """在起后台任务之前先把能查的查掉。

    否则参数错误会变成「HTTP 200 然后后台静默失败」，比直接报错难查得多。
    """
    load_graph_config(config.runs_dir, run_id)  # 非法 id / 不存在 -> RunNotFound
    state_path = Path(config.runs_dir) / run_id / STATE_FILENAME
    if not state_path.is_file():
        raise FileNotFoundError(f"{run_id} 没有可继续的状态（找不到 state.json）")


def _new_run(
    config: HarnessConfig,
    goal: str,
    session_id: str | None,
    cancel_token,
    on_event=None,
):
    """网页上发起一次新运行。"""
    from .runner import Harness

    harness = Harness(config)
    try:
        return harness.run_sync(
            goal,
            session_id=session_id,
            cancel_token=cancel_token,
            on_event=on_event,
        )
    finally:
        harness.close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "HarnessRuns"
    protocol_version = "HTTP/1.1"

    @property
    def runs_dir(self) -> Path:
        return self.server.runs_dir  # type: ignore[attr-defined]

    @property
    def config(self) -> HarnessConfig:
        return self.server.config  # type: ignore[attr-defined]

    @property
    def tasks(self) -> TaskRegistry:
        return self.server.tasks  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html", "/app"):
                self._send(
                    200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8"
                )
            elif path == "/api/status":
                self._json(_status_payload(self.config))
            elif path == "/api/runs":
                self._json({"runs": [item.as_dict() for item in list_runs(self.runs_dir)]})
            elif path == "/api/sessions":
                self._json(
                    {"sessions": [item.as_dict() for item in list_sessions(self.runs_dir)]}
                )
            elif path == "/api/tasks":
                task = self.tasks.get()
                self._json({"task": task.as_dict() if task else None})
            elif path.startswith("/api/runs/"):
                run_id = unquote(path[len("/api/runs/") :])
                self._json(load_run(self.runs_dir, run_id))
            else:
                self._json({"error": "not found"}, 404)
        except RunNotFound as exc:
            self._json({"error": str(exc)}, 404)
        except Exception as exc:  # 兜底，避免一个坏请求打断服务
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        # 这是整个服务唯一的写操作，而且会真的跑模型、可能执行命令。
        # 要求一个自定义请求头：跨域请求带自定义头会先发预检，
        # 而我们不响应预检，浏览器就会把恶意页面发起的请求挡在门外。
        if self.headers.get(ACTION_HEADER) != "1":
            self._json({"error": f"缺少 {ACTION_HEADER} 请求头"}, 403)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""  # 读掉 body，避免连接错位

        path = urlparse(self.path).path
        if path == "/api/runs":
            self._start_new_run(raw)
            return
        if path == "/api/tasks/cancel":
            if self.tasks.cancel_current():
                self._json({"ok": True, "cancelling": True})
            else:
                self._json({"error": "当前没有在跑的任务"}, 409)
            return

        match = ACTION_PATTERN.match(path)
        if not match:
            self._json({"error": "not found"}, 404)
            return

        run_id = unquote(match.group(1))
        action = match.group(2)
        # resume 和 approve 是同一件事：都是从 state.json 继续。
        # 区别只在于被停止的运行没有待批准项，那就纯粹接着跑。
        approve = action in ("approve", "resume")

        if action == "discard":
            # 不需要模型，也不用起后台任务 —— 只是把状态标记删掉
            try:
                discard_run(self.config.runs_dir, run_id)
            except RunNotFound as exc:
                self._json({"error": str(exc)}, 404)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, 409)
            else:
                self._json({"ok": True, "discarded": True})
            return
        try:
            _validate_resumable(self.config, run_id)
        except RunNotFound as exc:
            self._json({"error": str(exc)}, 404)
            return
        except FileNotFoundError as exc:
            self._json({"error": str(exc)}, 409)
            return

        def run(cancel_token, note):
            return _resume_run(
                self.config, run_id, approve, cancel_token, _progress_note(note)
            )

        try:
            task = self.tasks.start(run_id, f"{action} {run_id}", run)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 409)
        else:
            # 立刻返回。页面靠轮询 /api/tasks 看进度，也可以随时叫停。
            self._json({"ok": True, "started": True, "task": task.as_dict()})

    def _start_new_run(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "请求体不是合法 JSON"}, 400)
            return
        if not isinstance(payload, dict):
            self._json({"error": "请求体必须是一个对象"}, 400)
            return

        goal = str(payload.get("goal") or "").strip()
        if not goal:
            self._json({"error": "goal 不能为空"}, 400)
            return

        session_id = payload.get("session_id") or None
        if session_id:
            try:
                validate_session_id(str(session_id))
            except InvalidSessionId as exc:
                self._json({"error": str(exc)}, 400)
                return
            session_id = str(session_id)

        # shell 权限跟着服务启动时的配置走，网页不能临时打开它 ——
        # 那等于让浏览器提权。想跑命令就用 --allow-shell 起服务。
        config = self.config

        def run(cancel_token, note):
            return _new_run(
                config, goal, session_id, cancel_token, _progress_note(note)
            )

        try:
            task = self.tasks.start(key="new", label=f"新任务 {goal[:24]}", fn=run)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 409)
        else:
            self._json({"ok": True, "started": True, "task": task.as_dict()})

    def log_message(self, *args: Any) -> None:
        """默认会往 stderr 刷每一条请求，太吵。"""
        return


class RunsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: HarnessConfig, host: str, port: int) -> None:
        super().__init__((host, port), _Handler)
        self.config = config
        self.runs_dir = Path(config.runs_dir)
        self.tasks = TaskRegistry()


def serve(
    config: HarnessConfig, host: str = "127.0.0.1", port: int = DEFAULT_PORT
) -> RunsServer:
    """创建服务但不启动。调用方负责 serve_forever / shutdown。"""
    if not (WEB_DIR / "index.html").is_file():
        raise FileNotFoundError(f"前端文件缺失: {WEB_DIR / 'index.html'}")
    return RunsServer(config, host, port)


__all__ = [
    "ACTION_HEADER",
    "ACTION_PATTERN",
    "DEFAULT_PORT",
    "RunsServer",
    "WEB_DIR",
    "serve",
]
