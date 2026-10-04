from __future__ import annotations

from harness import config as config_module
from harness import provider
from harness.config import HarnessConfig


def test_compatible_endpoint_client_gets_timeout_and_retry_policy(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(provider, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(
        provider,
        "OpenAIChatCompletionsModel",
        lambda **kwargs: kwargs,
    )

    result = provider.build_model(
        HarnessConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            workspace=tmp_path / "ws",
            model_timeout=37.5,
            model_max_retries=2,
        )
    )

    assert captured == {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "timeout": 37.5,
        "max_retries": 2,
    }
    assert result["model"] == config_module.DEFAULT_MODEL
