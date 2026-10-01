"""验证 OpenAI 兼容端点（DeepSeek 走的就是这条路）真的能跑通。

不需要 API key：起一个本地假端点，让 harness 真的发 HTTP 请求过去，
再把收到的 payload 抓下来检查。这样能在花钱之前确认请求形状是对的。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness import Harness, HarnessConfig


def _chat_response(message: dict, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
    }


def _tool_call(name: str, arguments: dict, call_id: str) -> dict:
    return _chat_response(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        },
        finish_reason="tool_calls",
    )


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append({"path": self.path, "body": body})

        index = len(self.server.requests) - 1
        script = self.server.responses
        payload = script[index] if index < len(script) else script[-1]
        raw = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # 静音
        return


class FakeEndpoint:
    """本地假端点，记录收到的所有请求。"""

    def __init__(self, responses: list[dict]) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.requests = []
        self.server.responses = responses
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> FakeEndpoint:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict]:
        return self.server.requests


async def test_deepseek_style_endpoint_drives_the_whole_flow(tmp_path):
    responses = [
        _tool_call("researcher", {"input": "看看工作区"}, "call_1"),
        _chat_response({"role": "assistant", "content": "工作区是空的。"}),
        _chat_response({"role": "assistant", "content": "结论：工作区为空。"}),
    ]

    with FakeEndpoint(responses) as endpoint:
        config = HarnessConfig(
            model="deepseek-flash",
            api_key="test-key",
            base_url=endpoint.base_url,
            workspace=tmp_path / "ws",
            runs_dir=tmp_path / "runs",
            tracing="local",
        )
        outcome = await Harness(config).run("看看工作区")

    assert "结论" in outcome.final_output
    assert len(endpoint.requests) == 3

    # 走的是 Chat Completions，不是 Responses API
    assert all(r["path"].endswith("/chat/completions") for r in endpoint.requests)

    first = endpoint.requests[0]["body"]
    assert first["model"] == "deepseek-flash"
    sent_tools = {t["function"]["name"] for t in first["tools"]}
    assert sent_tools == {"researcher", "coder", "reviewer"}


async def test_deepseek_gets_non_strict_tool_schemas(tmp_path):
    """DeepSeek 不支持 OpenAI 的 strict 函数模式，默认必须不发送 strict=True。

    注意 as_tool() 生成的 worker 工具会强制 strict_json_schema=True，
    必须靠 apply_strict_policy 在构造后覆盖掉。
    """
    responses = [_chat_response({"role": "assistant", "content": "ok"})]

    with FakeEndpoint(responses) as endpoint:
        config = HarnessConfig(
            model="deepseek-flash",
            api_key="test-key",
            base_url=endpoint.base_url,
            workspace=tmp_path / "ws",
            runs_dir=tmp_path / "runs",
        )
        await Harness(config).run("随便问一句")

    tools = endpoint.requests[0]["body"]["tools"]
    assert tools
    for tool in tools:
        assert tool["function"].get("strict") is not True, tool["function"]["name"]

    # 覆盖到全部的工具体系：委派工具和文件工具都要被管住
    names = {t["function"]["name"] for t in tools}
    assert names == {"researcher", "coder", "reviewer"}


async def test_thinking_can_be_disabled_for_deepseek(tmp_path):
    """HARNESS_THINKING=disabled 应该真的通过 extra_body 发出去。"""
    responses = [_chat_response({"role": "assistant", "content": "ok"})]

    with FakeEndpoint(responses) as endpoint:
        config = HarnessConfig(
            model="deepseek-flash",
            api_key="test-key",
            base_url=endpoint.base_url,
            workspace=tmp_path / "ws",
            runs_dir=tmp_path / "runs",
            thinking="disabled",
        )
        await Harness(config).run("随便问一句")

    assert endpoint.requests[0]["body"]["thinking"] == {"type": "disabled"}


async def test_unsupported_parameters_are_not_sent(tmp_path):
    """确认没有把 DeepSeek 不认的参数发出去。"""
    responses = [_chat_response({"role": "assistant", "content": "ok"})]

    with FakeEndpoint(responses) as endpoint:
        config = HarnessConfig(
            model="deepseek-flash",
            api_key="test-key",
            base_url=endpoint.base_url,
            workspace=tmp_path / "ws",
            runs_dir=tmp_path / "runs",
        )
        await Harness(config).run("随便问一句")

    body = endpoint.requests[0]["body"]
    for unsupported in ("store", "previous_response_id", "include", "truncation"):
        assert unsupported not in body, f"不该发送 {unsupported}"
