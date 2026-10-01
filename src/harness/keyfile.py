"""读写 .env 里的凭据。

单独拆出来是为了可测试：写入 key 是最容易出错、也最不该出错的一步。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
MAX_REASONABLE_KEY_LEN = 100


def clean_key(raw: str) -> str:
    """去掉首尾的引号/Bearer 前缀和外围空白。

    刻意不删除内部空白：内部出现换行或空格，通常意味着复制时把多行内容
    一起带进来了，那是必须让用户看到的信号，不能悄悄抹平。
    """
    key = raw.strip().strip("\"'").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def mask_key(key: str, *, head: int = 6, tail: int = 4) -> str:
    """只显示首尾，让用户自己确认有没有粘对。"""
    if not key:
        return "(空)"
    if len(key) <= head + tail:
        return f"{key[:1]}***（{len(key)} 字符）"
    return f"{key[:head]}…{key[-tail:]}（{len(key)} 字符）"


def read_lines(path: Path, *, template: Path | None = None) -> list[str]:
    if path.is_file():
        return path.read_text(encoding="utf-8").splitlines()
    if template is not None and template.is_file():
        return template.read_text(encoding="utf-8").splitlines()
    return [
        "HARNESS_MODEL=deepseek-flash",
        "HARNESS_API_KEY=",
        f"HARNESS_BASE_URL={DEFAULT_BASE_URL}",
    ]


def current_value(lines: list[str], name: str) -> str:
    """取未被注释的 name=... 的值；注释行会被忽略。"""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == name:
            return value.strip().strip("\"'").strip()
    return ""


def upsert(lines: list[str], name: str, value: str) -> list[str]:
    """替换未被注释的 name=... 行；不存在则追加到末尾。"""
    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if (
            not stripped.startswith("#")
            and "=" in stripped
            and stripped.partition("=")[0].strip() == name
        ):
            out.append(f"{name}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{name}={value}")
    return out


def write_value(
    path: Path,
    name: str,
    value: str,
    *,
    template: Path | None = None,
    allow_clear: bool = False,
) -> int:
    """写入一个配置项。

    默认拒绝用空值覆盖已有的非空值。这条防线是有代价换来的：
    一次「清理坏 key」的临时脚本写错了判断条件，把文件里刚验证通过的
    有效 key 直接清空了。清理必须是显式行为。
    """
    lines = read_lines(path, template=template)
    previous = current_value(lines, name)
    if not value and previous and not allow_clear:
        raise ValueError(
            f"拒绝用空值覆盖已存在的 {name}；确实要清空请显式传 allow_clear=True"
        )

    lines = upsert(lines, name, value)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines)


def verify_key(base_url: str, key: str, *, timeout: float = 30.0) -> tuple[bool, str]:
    """调用 /models 验证凭据。这一步不消耗 token。"""
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {exc.code}: {detail}"
    except Exception as exc:  # 网络不可达等
        return False, f"{type(exc).__name__}: {exc}"

    models = [m.get("id") for m in data.get("data", []) if m.get("id")]
    if models:
        return True, "可用模型: " + ", ".join(models)
    return True, "鉴权通过"


def key_warning(key: str) -> str | None:
    """常见的复制错误给出提示（不阻断写入）。"""
    if not key:
        return None
    if any(ch.isspace() for ch in key):
        return "内容里含有空白或换行，多半是把多行内容一起复制进来了"
    if key.count("sk-") > 1:
        return f"内容里有 {key.count('sk-')} 处 'sk-'，看起来是把多把 key 粘在了一起"
    if not key.startswith("sk-"):
        return f"这个 key 不是以 'sk-' 开头（长度 {len(key)}），确认没复制错。"
    if len(key) < 20:
        return f"这个 key 只有 {len(key)} 个字符，看起来偏短（多半是占位符或没复制全）。"
    if len(key) > MAX_REASONABLE_KEY_LEN:
        return (
            f"这个 key 有 {len(key)} 个字符，太长了"
            f"（DeepSeek 的 key 通常是 35 个字符左右）。"
        )
    return None


__all__ = [
    "DEFAULT_BASE_URL",
    "MAX_REASONABLE_KEY_LEN",
    "clean_key",
    "current_value",
    "key_warning",
    "mask_key",
    "read_lines",
    "upsert",
    "verify_key",
    "write_value",
]
