from __future__ import annotations

from harness.config import HarnessConfig


def test_from_env_reads_dotenv_file(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        "HARNESS_MODEL=test-model\n"
        "HARNESS_BASE_URL=https://example.invalid/v1\n"
        "HARNESS_API_KEY=test-key\n"
        "HARNESS_MAX_TURNS=5\n"
        "HARNESS_SESSION_ITEM_LIMIT=17\n"
        "HARNESS_MODEL_TIMEOUT=45\n"
        "HARNESS_MODEL_MAX_RETRIES=3\n"
        "HARNESS_ROUTING=off\n"
        "HARNESS_FAST_PATH_MAX_TURNS=5\n"
        "HARNESS_DEDUPE_TOOLS=1\n"
        "HARNESS_TOOL_OUTPUT_CHARS=12000\n",
        encoding="utf-8",
    )
    for key in (
        "HARNESS_MODEL",
        "HARNESS_BASE_URL",
        "HARNESS_API_KEY",
        "HARNESS_MAX_TURNS",
        "HARNESS_SESSION_ITEM_LIMIT",
        "HARNESS_MODEL_TIMEOUT",
        "HARNESS_MODEL_MAX_RETRIES",
        "HARNESS_ROUTING",
        "HARNESS_FAST_PATH_MAX_TURNS",
        "HARNESS_DEDUPE_TOOLS",
        "HARNESS_TOOL_OUTPUT_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)

    config = HarnessConfig.from_env(env_file=env_file, workspace=tmp_path / "ws")

    assert config.model == "test-model"
    assert config.base_url == "https://example.invalid/v1"
    assert config.resolved_api_key == "test-key"
    assert config.max_turns == 5
    assert config.session_item_limit == 17
    assert config.model_timeout == 45
    assert config.model_max_retries == 3
    assert config.routing_mode == "off"
    assert config.fast_path_max_turns == 5
    assert config.dedupe_tools is True
    assert config.tool_output_chars == 12000
    assert config.env_file == env_file.resolve()


def test_explicit_overrides_win_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MODEL", "from-env")

    config = HarnessConfig.from_env(
        env_file=None, model="from-flag", workspace=tmp_path / "ws"
    )

    assert config.model == "from-flag"
    assert config.env_file is None


def test_paths_are_resolved_to_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    config = HarnessConfig.from_env(env_file=None)

    assert config.workspace.is_absolute()
    assert config.runs_dir.is_absolute()


def test_invalid_tracing_mode_is_rejected(tmp_path):
    try:
        HarnessConfig(tracing="nope", workspace=tmp_path / "ws")
    except ValueError as exc:
        assert "tracing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("非法 tracing 模式应该报错")


def test_negative_session_item_limit_is_rejected(tmp_path):
    try:
        HarnessConfig(session_item_limit=-1, workspace=tmp_path / "ws")
    except ValueError as exc:
        assert "session_item_limit" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("负数会话窗口应该报错")


def test_invalid_model_timeout_is_rejected(tmp_path):
    try:
        HarnessConfig(model_timeout=0, workspace=tmp_path / "ws")
    except ValueError as exc:
        assert "model_timeout" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("非正数模型超时应该报错")


def test_negative_model_retries_are_rejected(tmp_path):
    try:
        HarnessConfig(model_max_retries=-1, workspace=tmp_path / "ws")
    except ValueError as exc:
        assert "model_max_retries" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("负数重试次数应该报错")


def test_invalid_routing_mode_is_rejected(tmp_path):
    try:
        HarnessConfig(routing_mode="sometimes", workspace=tmp_path / "ws")
    except ValueError as exc:
        assert "routing_mode" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("非法 routing_mode 应该报错")
