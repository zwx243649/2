"""本地只读服务：把 runs/ 用网页展示出来。

刻意只用标准库：这是一个本地查看器，不值得为它引入 Web 框架。
默认绑定 127.0.0.1 —— runs/ 里含完整的 prompt 和产出，不该暴露到网络上。
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import HarnessConfig
from .runs_index import RunNotFound, list_runs, list_sessions, load_run

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8765

ACTION_PATTERN = re.compile(r"^/api/runs/([^/]+)/(approve|reject)$")
ACTION_HEADER = "X-Harness-Action"

# 一次只允许一个写操作。Harness 的追踪开关是进程级全局状态，
# 并发跑两个会让它们互相覆盖。
_ACTION_LOCK = threading.Lock()


def _resume_run(config: HarnessConfig, run_id: str, approve: bool):
    """执行一次批准/拒绝。放在函数里是为了延迟导入 agents SDK ——
    只看历史的话根本不需要把它加载起来。"""
    from .runner import Harness
    from .runs_index import load_graph_config

    stored = load_graph_config(config.runs_dir, run_id)
    resolved = config.with_overrides(**stored) if stored else config

    harness = Harness(resolved)
    try:
        return harness.resume_sync(run_id, approve=approve)
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
            if path in ("/", "/index.html"):
                self._send(
                    200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8"
                )
            elif path == "/api/runs":
                self._json({"runs": [item.as_dict() for item in list_runs(self.runs_dir)]})
            elif path == "/api/sessions":
                self._json(
                    {"sessions": [item.as_dict() for item in list_sessions(self.runs_dir)]}
                )
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
        if length:
            self.rfile.read(length)  # 读掉 body，避免 keep-alive 连接错位

        match = ACTION_PATTERN.match(urlparse(self.path).path)
        if not match:
            self._json({"error": "not found"}, 404)
            return

        run_id = unquote(match.group(1))
        approve = match.group(2) == "approve"

        try:
            with _ACTION_LOCK:
                outcome = _resume_run(self.config, run_id, approve)
        except RunNotFound as exc:
            self._json({"error": str(exc)}, 404)
        except FileNotFoundError as exc:
            self._json({"error": str(exc)}, 409)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        else:
            self._json(
                {
                    "ok": True,
                    "run_id": outcome.run_id,
                    "status": outcome.status,
                    "final_output": outcome.final_output,
                    "pending": outcome.pending,
                }
            )

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
