from __future__ import annotations

from harness.config import HarnessConfig


def test_from_env_reads_dotenv_file(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        "HARNESS_MODEL=test-model\n"
        "HARNESS_BASE_URL=https://example.invalid/v1\n"
        "HARNESS_API_KEY=test-key\n"
        "HARNESS_MAX_TURNS=5\n",
        encoding="utf-8",
    )
    for key in (
        "HARNESS_MODEL",
        "HARNESS_BASE_URL",
        "HARNESS_API_KEY",
        "HARNESS_MAX_TURNS",
    ):
        monkeypatch.delenv(key, raising=False)

    config = HarnessConfig.from_env(env_file=env_file, workspace=tmp_path / "ws")

    assert config.model == "test-model"
    assert config.base_url == "https://example.invalid/v1"
    assert config.resolved_api_key == "test-key"
    assert config.max_turns == 5
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
