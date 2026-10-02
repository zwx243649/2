"""交互式把 API key 写进 .env。

  - 输入不回显，key 不会进终端历史、聊天记录或日志
  - 不需要手工编辑文件，避免改错文件 / 忘记保存
  - 写入后立刻用 /models 验证一次，这步不消耗 token

用法:
    .\\.venv\\Scripts\\python.exe scripts\\set_key.py
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from harness.keyfile import (  # noqa: E402
    DEFAULT_BASE_URL,
    clean_key,
    current_value,
    key_warning,
    mask_key,
    read_lines,
    verify_key,
    write_value,
)
from harness.console import force_utf8_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_TEMPLATE = ROOT / ".env.example"
KEY_NAME = "HARNESS_API_KEY"


def main() -> int:
    parser = argparse.ArgumentParser(description="交互式把 API key 写进 .env")
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使 key 看起来不合法也写入（默认拒绝）",
    )
    args = parser.parse_args()

    force_utf8_stdout()

    lines = read_lines(ENV_FILE, template=ENV_TEMPLATE)
    base_url = current_value(lines, "HARNESS_BASE_URL") or DEFAULT_BASE_URL
    model = current_value(lines, "HARNESS_MODEL") or "(未设置)"
    existing = current_value(lines, KEY_NAME)

    print(f"配置文件 : {ENV_FILE}")
    print(f"端点     : {base_url}")
    print(f"模型     : {model}")
    print(f"当前 key : {'已设置' if existing else '空'}")
    print()
    print("粘贴你的 API key 然后回车（输入不会回显）：")

    try:
        key = clean_key(getpass.getpass("API key: "))
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        return 130

    if not key:
        print("没有输入任何内容，已取消。")
        return 1

    print(f"\n收到: {mask_key(key)}")

    warning = key_warning(key)
    if warning:
        # 防手滑的关键一层：宁可拒绝写入，也不能让一个明显错误的输入
        # 覆盖掉文件里原本有效的 key。
        if not args.force:
            print(f"\n已拒绝写入：{warning}")
            print("这看起来不是有效的 API key。确认无误的话加 --force 重试。")
            print("（文件没有被改动）")
            return 1
        print(f"提示：{warning}（--force 已指定，仍然写入）")

    write_value(ENV_FILE, KEY_NAME, key, template=ENV_TEMPLATE)
    print(f"\n已写入 {ENV_FILE}（{KEY_NAME}，{len(key)} 字符）")

    print("正在验证（调用 /models，不消耗 token）...")
    ok, message = verify_key(base_url, key)
    if ok:
        print(f"验证通过。{message}")
        print(r"下一步：.\.venv\Scripts\python.exe -m harness --dry-run")
        return 0

    # 验证不过就回滚，绝不把一把坏 key 留在配置里
    write_value(
        ENV_FILE, KEY_NAME, existing, template=ENV_TEMPLATE, allow_clear=True
    )
    print(f"验证失败：{message}")
    print(f"已回滚：{KEY_NAME} 恢复为原来的值（{'空' if not existing else '原 key'}）。")
    print("请确认 key 有效、账号已充值。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
