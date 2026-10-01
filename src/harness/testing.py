"""可脚本化的假模型：用来在不花钱、不联网的情况下测试编排链路。

它同时也是「怎么自己实现一个 Model」的最小参考——
注意 generation_span 必须自己开，SDK 不会替自定义模型包这一层。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agents import Model, ModelResponse, ModelTracing, Usage, generation_span
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseUsage,
)
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails

# 假模型固定上报这两个数，便于测试断言
FAKE_INPUT_TOKENS = 100
FAKE_OUTPUT_TOKENS = 20


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

    def __init__(
        self,
        responses: list[ModelResponse],
        name: str = "scripted-model",
        delay: float = 0.0,
    ) -> None:
        self.responses = list(responses)
        self.name = name
        # 让每次调用慢下来，用于测试取消
        self.delay = delay
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
        self._record_call(system_instructions, input, tools)

        with generation_span(model=self.name, disabled=tracing.is_disabled()) as span:
            response = self._next_response()
            self._fill_span(span, response, tracing)
            return response

    async def stream_response(
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
    ) -> Any:
        """流式版本。

        运行循环要的是一个 ResponseCompletedEvent（带完整 output 和 usage），
        少了它会报 "Model did not produce a final response"。
        中间的 delta 事件对最终结果没影响，所以这里只发终止事件。
        """
        self._record_call(system_instructions, input, tools)

        with generation_span(model=self.name, disabled=tracing.is_disabled()) as span:
            response = self._next_response()
            self._fill_span(span, response, tracing)
            if self.delay:
                await asyncio.sleep(self.delay)
            yield ResponseCompletedEvent(
                type="response.completed",
                sequence_number=0,
                response=Response(
                    id=response.response_id or "resp_scripted",
                    created_at=0,
                    model=self.name,
                    object="response",
                    output=list(response.output),
                    parallel_tool_calls=False,
                    tool_choice="auto",
                    tools=[],
                    usage=ResponseUsage(
                        input_tokens=FAKE_INPUT_TOKENS,
                        output_tokens=FAKE_OUTPUT_TOKENS,
                        total_tokens=FAKE_INPUT_TOKENS + FAKE_OUTPUT_TOKENS,
                        input_tokens_details=InputTokensDetails(
                            cached_tokens=0, cache_write_tokens=0
                        ),
                        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                    ),
                ),
            )

    # ---- 内部 ----

    def _record_call(
        self, system_instructions: Any, input: Any, tools: list[Any]
    ) -> None:
        self.calls.append(
            {
                "agent_instructions": system_instructions,
                "tools": sorted(tool.name for tool in tools),
                # 保留原始输入，便于断言「会话上下文有没有带上」
                "input_items": list(input)
                if isinstance(input, list)
                else [{"role": "user", "content": input}],
            }
        )

    def _next_response(self) -> ModelResponse:
        if self.responses:
            return self.responses.pop(0)
        return text_response("[scripted model exhausted]", response_id="resp_exhausted")

    def _fill_span(
        self, span: Any, response: ModelResponse, tracing: ModelTracing
    ) -> None:
        if tracing.include_data():
            span.span_data.output = [item.model_dump() for item in response.output]
        span.span_data.usage = {
            "requests": 1,
            "input_tokens": FAKE_INPUT_TOKENS,
            "output_tokens": FAKE_OUTPUT_TOKENS,
            "total_tokens": FAKE_INPUT_TOKENS + FAKE_OUTPUT_TOKENS,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }


__all__ = ["ScriptedModel", "text_response", "tool_call_response"]
