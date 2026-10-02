"""校验用例是否合格 —— 跑评估之前先过一遍，别把钱花在坏用例上。

检查：
  1. meta.json / workspace/ / verify/ 齐不齐
  2. 起始状态必须是失败的（不然没有可修的）
  3. 隐藏测试必须真的被 pytest 收集到（名字不对就白写了）
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "evals" / "tasks"
REQUIRED = ("id", "goal", "category", "difficulty")
COLLECTED = re.compile(r"(\d+)\s+tests?\s+collected")


def prepare(task_dir: Path, *, with_hidden: bool) -> Path:
    root = Path(tempfile.mkdtemp(prefix="check-"))
    workspace = root / "workspace"
    shutil.copytree(task_dir / "workspace", workspace)
    if with_hidden:
        for path in (task_dir / "verify").rglob("*.py"):
            stem = path.stem.removeprefix("test_")
            shutil.copy(path, workspace / f"test_hidden_{stem}.py")
    return workspace


def run_pytest(workspace: Path) -> tuple[int, int, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(workspace),
        capture_output=True,
    )
    output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    # pytest 的退出码：0 全过，1 有用例失败，2 收集/内部错误
    return completed.returncode, len(output), tail


def count_collected(workspace: Path) -> int:
    """数一下 pytest 到底会收集多少个用例。

    不能用输出长度当代理 —— 失败信息的长短会让它误判。
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(workspace),
        capture_output=True,
    )
    output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    match = COLLECTED.search(output)
    if match:
        return int(match.group(1))
    # 老版本会只列 id，按行数兜底
    return sum(1 for line in output.splitlines() if "::" in line)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    problems: list[str] = []
    tasks = sorted(p for p in TASKS_DIR.iterdir() if p.is_dir())
    print(f"检查 {len(tasks)} 个用例\n")

    for task_dir in tasks:
        name = task_dir.name
        meta_path = task_dir / "meta.json"
        if not meta_path.is_file():
            problems.append(f"{name}: 缺 meta.json")
            print(f"  ✗ {name}: 缺 meta.json")
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED if k not in meta]
        if missing:
            problems.append(f"{name}: meta 缺字段 {missing}")

        if not (task_dir / "workspace").is_dir():
            problems.append(f"{name}: 缺 workspace/")
            print(f"  ✗ {name}: 缺 workspace/")
            continue
        if not (task_dir / "verify").is_dir() or not list(
            (task_dir / "verify").rglob("*.py")
        ):
            problems.append(f"{name}: 缺 verify/ 里的隐藏测试")
            print(f"  ✗ {name}: 没写隐藏测试")
            continue

        # 1. 起始状态必须失败
        code, _, tail = run_pytest(prepare(task_dir, with_hidden=False))
        if code == 0:
            problems.append(f"{name}: 起始状态就是通过的，没有可修的")
            print(f"  ✗ {name}: 起始状态全过 —— 用例无效")
            continue
        if code != 1:
            problems.append(f"{name}: 起始状态 pytest 出错（收集失败？）: {tail[:60]}")
            print(f"  ✗ {name}: 收集出错 {tail[:60]}")
            continue

        # 2. 加上隐藏测试后，收集到的用例数必须变多
        alone = count_collected(prepare(task_dir, with_hidden=False))
        together = count_collected(prepare(task_dir, with_hidden=True))
        if together <= alone:
            problems.append(f"{name}: 隐藏测试没被收集到（{alone} -> {together}）")
            print(f"  ✗ {name}: 隐藏测试没被收集（{alone} -> {together}）")
            continue

        _, _, visible_tail = run_pytest(prepare(task_dir, with_hidden=False))
        print(f"  ✓ {name:<26} 用例 {alone} -> {together}   {visible_tail[:30]}")

    print()
    if problems:
        print(f"发现 {len(problems)} 个问题:")
        for item in problems:
            print("  -", item)
        return 1
    print("全部合格。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
