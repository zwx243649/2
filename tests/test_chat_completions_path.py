"""验证 OpenAI 兼容端点（DeepSeek 走的就是这条路）真的能跑通。

不需要 API key：起一个本地假端点，让 harness 真的发 HTTP 请求过去，
再把收到的 payload 抓下来检查。这样能在花钱之前确认请求形状是对的。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness import Harness, HarnessConfig


def _chunk(delta: dict, finish_reason: str | None = None) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _usage_chunk() -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": "deepseek-flash",
        "choices": [],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
    }


def chat_stream(text: str) -> list[dict]:
    """一段纯文本回复的 SSE 分片。"""
    return [
        _chunk({"role": "assistant", "content": text}),
        _chunk({}, "stop"),
    ]


def tool_stream(name: str, arguments: dict, call_id: str) -> list[dict]:
    """一次工具调用的 SSE 分片。"""
    return [
        _chunk(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            }
        ),
        _chunk({}, "tool_calls"),
    ]


def to_sse(chunks: list[dict], *, include_usage: bool) -> bytes:
    """真正的 Chat Completions 流是 SSE，不是一次性 JSON。"""
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    if include_usage:
        lines.append(f"data: {json.dumps(_usage_chunk())}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append({"path": self.path, "body": body})

        index = len(self.server.requests) - 1
        script = self.server.responses
        chunks = script[index] if index < len(script) else script[-1]
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        raw = to_sse(chunks, include_usage=include_usage)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
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
        tool_stream("researcher", {"input": "看看工作区"}, "call_1"),
        chat_stream("工作区是空的。"),
        chat_stream("结论：工作区为空。"),
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
    responses = [chat_stream("ok")]

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
    responses = [chat_stream("ok")]

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
    responses = [chat_stream("ok")]

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
