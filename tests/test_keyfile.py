from __future__ import annotations

import pytest

from harness.keyfile import (
    clean_key,
    current_value,
    key_warning,
    mask_key,
    read_lines,
    upsert,
    write_value,
)

SAMPLE = [
    "# HARNESS_API_KEY=sk-commented-should-be-ignored",
    "HARNESS_MODEL=deepseek-flash",
    "HARNESS_API_KEY=",
    "HARNESS_BASE_URL=https://api.deepseek.com",
]

VALID_KEY = "sk-" + "a1b2c3d4e5" * 3


def test_clean_key_strips_quotes_bearer_and_outer_whitespace():
    assert clean_key("  sk-abc123  ") == "sk-abc123"
    assert clean_key('"sk-abc123"') == "sk-abc123"
    assert clean_key("'sk-abc123'") == "sk-abc123"
    assert clean_key("Bearer sk-abc123") == "sk-abc123"
    assert clean_key("bearer  sk-abc123 ") == "sk-abc123"


def test_clean_key_preserves_internal_whitespace():
    """内部空白是「粘多了」的信号，必须保留，不能悄悄抹平。

    旧版本会把空白全部删掉，结果把用户复制的 8 把 key 粘成了一整块，
    掩盖了错误，直到服务端返回 401 才暴露。
    """
    assert clean_key("sk-abc 123") == "sk-abc 123"
    assert clean_key("sk-aaa\nsk-bbb") == "sk-aaa\nsk-bbb"


def test_current_value_ignores_commented_lines():
    assert current_value(SAMPLE, "HARNESS_API_KEY") == ""
    assert current_value(SAMPLE, "HARNESS_MODEL") == "deepseek-flash"


def test_upsert_replaces_in_place_and_keeps_comments():
    out = upsert(SAMPLE, "HARNESS_API_KEY", "sk-real")

    assert len(out) == len(SAMPLE)
    assert "HARNESS_API_KEY=sk-real" in out
    # 注释行不能被改掉
    assert "# HARNESS_API_KEY=sk-commented-should-be-ignored" in out
    # 只应该有一条生效的赋值
    assert sum(1 for line in out if line.startswith("HARNESS_API_KEY=")) == 1


def test_upsert_appends_when_missing():
    out = upsert(["HARNESS_MODEL=deepseek-flash"], "HARNESS_API_KEY", "sk-real")

    assert out[-1] == "HARNESS_API_KEY=sk-real"


def test_write_value_creates_file_from_template(tmp_path):
    template = tmp_path / ".env.example"
    template.write_text("\n".join(SAMPLE) + "\n", encoding="utf-8")
    target = tmp_path / ".env"

    write_value(target, "HARNESS_API_KEY", "sk-real", template=template)

    assert target.is_file()
    assert "HARNESS_API_KEY=sk-real" in target.read_text(encoding="utf-8")


def test_read_lines_falls_back_to_template(tmp_path):
    template = tmp_path / ".env.example"
    template.write_text("HARNESS_MODEL=from-template\n", encoding="utf-8")

    lines = read_lines(tmp_path / "missing.env", template=template)

    assert lines == ["HARNESS_MODEL=from-template"]


def test_key_warning_flags_placeholders():
    assert key_warning("") is None
    assert key_warning("sk-...") is not None
    assert key_warning("notaskey") is not None
    assert key_warning("sk-" + "x" * 32) is None


def test_key_warning_detects_concatenated_keys():
    """复现真实事故：用户一次复制了多把 key，拼成 250 字符。"""
    concatenated = "sk-" + "x" * 30 + "sk-" + "y" * 30

    warning = key_warning(concatenated)

    assert warning is not None
    assert "多把 key" in warning


def test_key_warning_detects_oversized_key():
    warning = key_warning("sk-" + "x" * 250)

    assert warning is not None
    assert "太长" in warning


def test_key_warning_detects_internal_whitespace():
    warning = key_warning("sk-abc def")

    assert warning is not None
    assert "空白" in warning


def test_key_warning_accepts_realistic_key():
    assert key_warning("sk-" + "a1b2c3d4e5" * 3) is None


def test_mask_key_never_reveals_the_body():
    key = "sk-" + "x" * 32

    masked = mask_key(key)

    assert "x" * 32 not in masked
    assert masked.startswith("sk-")
    assert "35" in masked
    assert mask_key("") == "(空)"


def test_write_value_refuses_to_clear_an_existing_key(tmp_path):
    """真实事故回归：一次「清理」脚本把刚验证通过的有效 key 清空了。"""
    target = tmp_path / ".env"
    target.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="拒绝用空值覆盖"):
        write_value(target, "HARNESS_API_KEY", "")

    assert VALID_KEY in target.read_text(encoding="utf-8")


def test_write_value_allows_explicit_clear(tmp_path):
    target = tmp_path / ".env"
    target.write_text(f"HARNESS_API_KEY={VALID_KEY}\n", encoding="utf-8")

    write_value(target, "HARNESS_API_KEY", "", allow_clear=True)

    assert target.read_text(encoding="utf-8") == "HARNESS_API_KEY=\n"


def test_write_value_can_set_a_key_on_empty_file(tmp_path):
    target = tmp_path / ".env"
    target.write_text("HARNESS_API_KEY=\n", encoding="utf-8")

    write_value(target, "HARNESS_API_KEY", VALID_KEY)

    assert f"HARNESS_API_KEY={VALID_KEY}" in target.read_text(encoding="utf-8")
