"""对比多次评估结果，并给出置信区间。

单跑一次的 Pass@1 是个噪声很大的估计 —— 这个脚本把它放在
「n 这么小，区间其实有多宽」的背景里看。
"""

from __future__ import annotations

import argparse
import json
import contextlib
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "_out"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 置信区间。"""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def main() -> int:
    parser = argparse.ArgumentParser(description="对比评估结果并给出置信区间")
    parser.add_argument(
        "reports",
        nargs="*",
        type=Path,
        help="要对比的结果 JSON；省略时读取 evals/_out/*.json",
    )
    args = parser.parse_args()

    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    files = list(args.reports) if args.reports else sorted(OUT.glob("*.json"))
    if not files:
        print("还没有评估结果")
        return 1

    reports = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    names = [path.stem for path in files]

    all_ids = sorted({r["task_id"] for rep in reports for r in rep["results"]})
    print("用例 × 每次运行（✓ 通过 / ✗ 未通过 / ⚠ 改了文档串）\n")
    header = "  " + f"{'用例':<26}" + "".join(f"{n:>12}" for n in names)
    print(header)
    print("  " + "-" * (26 + 12 * len(names)))
    for task_id in all_ids:
        cells = []
        for rep in reports:
            item = next((r for r in rep["results"] if r["task_id"] == task_id), None)
            if item is None:
                cells.append("—")
            elif not item["passed"]:
                cells.append("✗")
            elif item.get("spec_modified"):
                cells.append("⚠")
            else:
                cells.append("✓")
        print("  " + f"{task_id:<26}" + "".join(f"{c:>12}" for c in cells))

    print()
    print("汇总\n")
    total_k = total_n = 0
    for name, rep in zip(names, reports, strict=True):
        k, n = rep["passed"], rep["total"]
        total_k += k
        total_n += n
        lo, hi = wilson(k, n)
        print(
            f"  {name:<12} Pass@1 {k}/{n} = {k / n:.0%}   "
            f"95% 置信区间 [{lo:.0%}, {hi:.0%}]"
        )

    lo, hi = wilson(total_k, total_n)
    print()
    print(f"  合并 {total_n} 次运行：{total_k}/{total_n} = {total_k / total_n:.0%}")
    print(f"  95% 置信区间 [{lo:.0%}, {hi:.0%}]")
    print()
    print(f"  区间宽 {hi - lo:.0%} —— 样本量 {total_n}。" +
          ("  太窄不了，这个数字不能写进简历。" if hi - lo > 0.2 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
