"""模型/Provider 构造。

一个 harness 最重要的解耦点：业务代码只认 ``Model`` 接口，
具体走哪家、用哪个协议，全部在这里决定。
"""

from __future__ import annotations

from agents import (
    AsyncOpenAI,
    Model,
    ModelSettings,
    OpenAIChatCompletionsModel,
    set_default_openai_key,
)

from .config import HarnessConfig


def build_model(config: HarnessConfig) -> str | Model:
    """返回 Agents SDK 可直接使用的模型。

    - 设置了 ``base_url``：走 OpenAI 兼容的 Chat Completions，
      适用于 DeepSeek / Kimi / 豆包 / vLLM / Ollama 等。
    - 没设置：返回模型名字符串，交给 SDK 默认的 OpenAI Provider（Responses API）。
    """
    if config.base_url:
        client = AsyncOpenAI(
            api_key=config.resolved_api_key or "not-needed",
            base_url=config.base_url,
            timeout=config.model_timeout,
            max_retries=config.model_max_retries,
        )
        return OpenAIChatCompletionsModel(model=config.model, openai_client=client)

    if config.resolved_api_key:
        set_default_openai_key(config.resolved_api_key)

    return config.model


def build_model_settings(config: HarnessConfig) -> ModelSettings:
    """构造所有 agent 共用的模型参数。

    DeepSeek 默认开启 thinking 模式（effort=high），每次工具调用都会先输出一段思维链，
    多轮委派下会明显变慢变贵。``HARNESS_THINKING=disabled`` 可以关掉它。
    其他厂商不认识这个字段，所以默认不动。
    """
    if config.thinking == "disabled":
        return ModelSettings(extra_body={"thinking": {"type": "disabled"}})
    return ModelSettings()
