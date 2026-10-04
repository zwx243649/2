"""运行配置：全部来自环境变量，命令行参数可覆盖。"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .sessions import DEFAULT_ITEM_LIMIT as DEFAULT_SESSION_ITEM_LIMIT

DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_MAX_TURNS = 12
DEFAULT_WORKER_MAX_TURNS = 8
DEFAULT_MODEL_TIMEOUT = 120.0
DEFAULT_MODEL_MAX_RETRIES = 1
DEFAULT_ROUTING_MODE = "auto"
DEFAULT_FAST_PATH_MAX_TURNS = 8
DEFAULT_TOOL_OUTPUT_CHARS = 24_000
DEFAULT_SHELL_TIMEOUT = 60.0
DEFAULT_ENV_FILE = ".env"
TRACING_MODES = ("local", "openai", "off")
THINKING_MODES = ("default", "disabled")
ROUTING_MODES = ("auto", "off", "always")


def _project_env_file() -> Path | None:
    """回退到项目根目录的 .env，让 harness 在别的目录下也能跑。"""
    candidate = Path(__file__).resolve().parents[2] / DEFAULT_ENV_FILE
    return candidate if candidate.is_file() else None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


@dataclass(frozen=True)
class HarnessConfig:
    """一次 harness 运行的全部可调参数。"""

    model: str = DEFAULT_MODEL
    api_key: str | None = None
    base_url: str | None = None
    workspace: Path = Path("./workspace")
    runs_dir: Path = Path("./runs")
    max_turns: int = DEFAULT_MAX_TURNS
    worker_max_turns: int = DEFAULT_WORKER_MAX_TURNS
    session_item_limit: int = DEFAULT_SESSION_ITEM_LIMIT
    model_timeout: float = DEFAULT_MODEL_TIMEOUT
    model_max_retries: int = DEFAULT_MODEL_MAX_RETRIES
    routing_mode: str = DEFAULT_ROUTING_MODE
    fast_path_max_turns: int = DEFAULT_FAST_PATH_MAX_TURNS
    dedupe_tools: bool = False
    tool_output_chars: int = DEFAULT_TOOL_OUTPUT_CHARS
    allow_shell: bool = False
    approve_shell: bool = True
    shell_timeout: float = DEFAULT_SHELL_TIMEOUT
    strict_tools: bool = False
    thinking: str = "default"
    tracing: str = "local"
    save_artifacts: bool = True
    env_file: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", Path(self.workspace).expanduser().resolve())
        object.__setattr__(self, "runs_dir", Path(self.runs_dir).expanduser().resolve())
        if self.env_file is not None:
            object.__setattr__(self, "env_file", Path(self.env_file).expanduser().resolve())
        if self.max_turns < 1:
            raise ValueError("max_turns 必须 >= 1")
        if self.worker_max_turns < 1:
            raise ValueError("worker_max_turns 必须 >= 1")
        if self.session_item_limit < 0:
            raise ValueError("session_item_limit 必须 >= 0")
        if self.model_timeout <= 0:
            raise ValueError("model_timeout 必须 > 0")
        if self.model_max_retries < 0:
            raise ValueError("model_max_retries 必须 >= 0")
        if self.routing_mode not in ROUTING_MODES:
            raise ValueError(f"routing_mode 必须是 {ROUTING_MODES} 之一，收到 {self.routing_mode!r}")
        if self.fast_path_max_turns < 1:
            raise ValueError("fast_path_max_turns 必须 >= 1")
        if self.tool_output_chars < 1_000:
            raise ValueError("tool_output_chars 必须 >= 1000")
        if self.tracing not in TRACING_MODES:
            raise ValueError(f"tracing 必须是 {TRACING_MODES} 之一，收到 {self.tracing!r}")
        if self.thinking not in THINKING_MODES:
            raise ValueError(f"thinking 必须是 {THINKING_MODES} 之一，收到 {self.thinking!r}")

    @classmethod
    def from_env(
        cls,
        env_file: str | os.PathLike[str] | None = DEFAULT_ENV_FILE,
        **overrides: Any,
    ) -> HarnessConfig:
        """读取 .env + 环境变量，overrides 中非 None 的项优先。"""
        resolved_env: Path | None = None
        if env_file is not None:
            resolved_env = Path(env_file).expanduser()
            if not resolved_env.is_file() and str(env_file) == DEFAULT_ENV_FILE:
                resolved_env = _project_env_file() or resolved_env
            load_dotenv(resolved_env, override=False)

        tracing = (os.getenv("HARNESS_TRACING") or "local").strip().lower()
        values: dict[str, Any] = {
            "model": os.getenv("HARNESS_MODEL") or DEFAULT_MODEL,
            "api_key": os.getenv("HARNESS_API_KEY") or None,
            "base_url": os.getenv("HARNESS_BASE_URL") or None,
            "workspace": Path(os.getenv("HARNESS_WORKSPACE") or "./workspace"),
            "runs_dir": Path(os.getenv("HARNESS_RUNS_DIR") or "./runs"),
            "max_turns": _env_int("HARNESS_MAX_TURNS", DEFAULT_MAX_TURNS),
            "worker_max_turns": _env_int(
                "HARNESS_WORKER_MAX_TURNS", DEFAULT_WORKER_MAX_TURNS
            ),
            "session_item_limit": _env_int(
                "HARNESS_SESSION_ITEM_LIMIT", DEFAULT_SESSION_ITEM_LIMIT
            ),
            "model_timeout": _env_float("HARNESS_MODEL_TIMEOUT", DEFAULT_MODEL_TIMEOUT),
            "model_max_retries": _env_int(
                "HARNESS_MODEL_MAX_RETRIES", DEFAULT_MODEL_MAX_RETRIES
            ),
            "routing_mode": (os.getenv("HARNESS_ROUTING") or DEFAULT_ROUTING_MODE)
            .strip()
            .lower(),
            "fast_path_max_turns": _env_int(
                "HARNESS_FAST_PATH_MAX_TURNS", DEFAULT_FAST_PATH_MAX_TURNS
            ),
            "dedupe_tools": _env_bool("HARNESS_DEDUPE_TOOLS", False),
            "tool_output_chars": _env_int(
                "HARNESS_TOOL_OUTPUT_CHARS", DEFAULT_TOOL_OUTPUT_CHARS
            ),
            "allow_shell": _env_bool("HARNESS_ALLOW_SHELL", False),
            "approve_shell": _env_bool("HARNESS_APPROVE_SHELL", True),
            "shell_timeout": _env_float("HARNESS_SHELL_TIMEOUT", DEFAULT_SHELL_TIMEOUT),
            "strict_tools": _env_bool("HARNESS_STRICT_TOOLS", False),
            "thinking": (os.getenv("HARNESS_THINKING") or "default").strip().lower(),
            "tracing": tracing,
            "env_file": resolved_env,
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    @property
    def resolved_api_key(self) -> str | None:
        return self.api_key or os.getenv("OPENAI_API_KEY") or None

    def with_overrides(self, **overrides: Any) -> HarnessConfig:
        """基于当前配置生成一份改过的副本（None 表示不改）。"""
        clean = {key: value for key, value in overrides.items() if value is not None}
        return replace(self, **clean) if clean else self

    @property
    def sessions_db(self) -> Path:
        """会话的对话历史数据库。放在 runs_dir 下，和运行产物在一起。"""
        return self.runs_dir / "sessions.db"
