"""针对 scripts/set_key.py 的回归测试。

起因：脚本曾把任何输入都当 key 写入。一次误操作把 .env 里有效的 key
覆盖成了 4 个字符的 "exit"，直接毁掉凭据。现在必须拒绝明显不合法的输入。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "set_key.py"
VALID_KEY = "sk-" + "x" * 32


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("set_key_under_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(tmp_path, monkeypatch):
    """把脚本重定向到一个临时 .env，并屏蔽掉真实的网络验证。"""
    module = load_script()
    env_file = tmp_path / ".env"
    template = tmp_path / ".env.example"
    template.write_text(
        "HARNESS_MODEL=deepseek-flash\n"
        "HARNESS_API_KEY=\n"
        "HARNESS_BASE_URL=https://api.deepseek.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module, "ENV_TEMPLATE", template)
    monkeypatch.setattr(module, "verify_key", lambda *a, **k: (True, "mock"))
    monkeypatch.setattr(sys, "argv", ["set_key.py"])
    module._env_file = env_file  # 方便断言
    return module


def feed(script, monkeypatch, value: str) -> None:
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": value)


def test_short_input_is_refused_and_file_untouched(script, monkeypatch):
    script._env_file.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")
    before = script._env_file.read_text(encoding="utf-8")
    feed(script, monkeypatch, "exit")

    assert script.main() == 1
    assert script._env_file.read_text(encoding="utf-8") == before


def test_non_sk_input_is_refused(script, monkeypatch):
    script._env_file.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")
    before = script._env_file.read_text(encoding="utf-8")
    feed(script, monkeypatch, "totally-not-a-key")

    assert script.main() == 1
    assert script._env_file.read_text(encoding="utf-8") == before


def test_empty_input_is_refused(script, monkeypatch):
    script._env_file.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")
    feed(script, monkeypatch, "")

    assert script.main() == 1
    assert VALID_KEY in script._env_file.read_text(encoding="utf-8")


def test_valid_key_is_written(script, monkeypatch):
    script._env_file.write_text("HARNESS_API_KEY=\n", encoding="utf-8")
    feed(script, monkeypatch, VALID_KEY)

    assert script.main() == 0
    assert f"HARNESS_API_KEY={VALID_KEY}" in script._env_file.read_text(encoding="utf-8")


def test_force_allows_suspicious_input(script, monkeypatch):
    script._env_file.write_text("HARNESS_API_KEY=\n", encoding="utf-8")
    feed(script, monkeypatch, "short")
    monkeypatch.setattr(sys, "argv", ["set_key.py", "--force"])

    # --force 仍然会写入，但这是显式选择的结果
    assert script.main() == 0
    assert "HARNESS_API_KEY=short" in script._env_file.read_text(encoding="utf-8")


def test_concatenated_keys_are_refused(script, monkeypatch):
    """真实事故回归：一次粘进 250 字符 / 8 把 key，必须拒绝且不动文件。"""
    script._env_file.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")
    before = script._env_file.read_text(encoding="utf-8")
    feed(script, monkeypatch, "sk-" + "x" * 30 + "sk-" + "y" * 30)

    assert script.main() == 1
    assert script._env_file.read_text(encoding="utf-8") == before


def test_failed_verification_rolls_back(script, monkeypatch):
    """鉴权失败时必须回滚，不能把坏 key 留在配置里。"""
    script._env_file.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")
    monkeypatch.setattr(script, "verify_key", lambda *a, **k: (False, "HTTP 401"))
    feed(script, monkeypatch, "sk-" + "y" * 32)

    assert script.main() == 1
    assert f"HARNESS_API_KEY={VALID_KEY}" in script._env_file.read_text(encoding="utf-8")


def test_failed_verification_restores_empty_state(script, monkeypatch):
    script._env_file.write_text("HARNESS_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(script, "verify_key", lambda *a, **k: (False, "HTTP 401"))
    feed(script, monkeypatch, "sk-" + "y" * 32)

    assert script.main() == 1
    assert "HARNESS_API_KEY=\n" in script._env_file.read_text(encoding="utf-8")
