"""可脚本化的假模型：用来在不花钱、不联网的情况下测试编排链路。

它同时也是「怎么自己实现一个 Model」的最小参考——
注意 generation_span 必须自己开，SDK 不会替自定义模型包这一层。
"""

from __future__ import annotations

import json
from typing import Any

from agents import Model, ModelResponse, ModelTracing, Usage, generation_span
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)


def text_response(body: str, response_id: str = "resp_text") -> ModelResponse:
    """构造一条助手文本回复。"""
    return ModelResponse(
        output=[
            ResponseOutputMessage(
                id=f"msg_{response_id}",
                type="message",
                role="assistant",
                status="completed",
                content=[ResponseOutputText(type="output_text", text=body, annotations=[])],
            )
        ],
        usage=Usage(),
        response_id=response_id,
    )


def tool_call_response(
    name: str,
    arguments: dict[str, Any],
    *,
    call_id: str = "call_1",
) -> ModelResponse:
    """构造一次工具/委派调用。"""
    return ModelResponse(
        output=[
            ResponseFunctionToolCall(
                id=f"fc_{call_id}",
                type="function_call",
                call_id=call_id,
                name=name,
                arguments=json.dumps(arguments, ensure_ascii=False),
                status="completed",
            )
        ],
        usage=Usage(),
        response_id=f"resp_{call_id}",
    )


class ScriptedModel(Model):
    """按顺序返回预置响应，并记录每次调用看到的工具列表。"""

    def __init__(self, responses: list[ModelResponse], name: str = "scripted-model") -> None:
        self.responses = list(responses)
        self.name = name
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        system_instructions: str | None,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        self.calls.append(
            {
                "agent_instructions": system_instructions,
                "tools": sorted(tool.name for tool in tools),
            }
        )

        with generation_span(model=self.name, disabled=tracing.is_disabled()) as span:
            if self.responses:
                response = self.responses.pop(0)
            else:
                response = text_response(
                    "[scripted model exhausted]", response_id="resp_exhausted"
                )
            if tracing.include_data():
                span.span_data.output = [item.model_dump() for item in response.output]
            span.span_data.usage = {
                "requests": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            }
            return response

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("ScriptedModel 只支持非流式调用")
        yield  # pragma: no cover


__all__ = ["ScriptedModel", "text_response", "tool_call_response"]
