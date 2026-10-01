"""本地只读服务：把 runs/ 用网页展示出来。

刻意只用标准库：这是一个本地查看器，不值得为它引入 Web 框架。
默认绑定 127.0.0.1 —— runs/ 里含完整的 prompt 和产出，不该暴露到网络上。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .runs_index import RunNotFound, list_runs, list_sessions, load_run

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8765


class _Handler(BaseHTTPRequestHandler):
    server_version = "HarnessRuns"
    protocol_version = "HTTP/1.1"

    @property
    def runs_dir(self) -> Path:
        return self.server.runs_dir  # type: ignore[attr-defined]

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

    def log_message(self, *args: Any) -> None:
        """默认会往 stderr 刷每一条请求，太吵。"""
        return


class RunsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, runs_dir: Path, host: str, port: int) -> None:
        super().__init__((host, port), _Handler)
        self.runs_dir = Path(runs_dir)


def serve(runs_dir: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> RunsServer:
    """创建服务但不启动。调用方负责 serve_forever / shutdown。"""
    if not (WEB_DIR / "index.html").is_file():
        raise FileNotFoundError(f"前端文件缺失: {WEB_DIR / 'index.html'}")
    return RunsServer(Path(runs_dir), host, port)


__all__ = ["DEFAULT_PORT", "RunsServer", "WEB_DIR", "serve"]
