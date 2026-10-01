"""离线演示：不用 API key，用脚本模型把 supervisor → worker 的完整流程跑一遍。

运行：python examples/offline_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from harness import Harness, HarnessConfig  # noqa: E402
from harness.progress import ConsoleReporter  # noqa: E402
from harness.testing import ScriptedModel, text_response, tool_call_response  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "_demo_output"


def build_model() -> ScriptedModel:
    """预演：supervisor 委派 researcher 调研 → 委派 coder 实现 → 自己汇总。"""
    return ScriptedModel(
        [
            # 1. supervisor 决定先调研
            tool_call_response(
                "researcher",
                {"input": "看一下工作区现状，确认要新建哪些文件。"},
                call_id="c1",
            ),
            # 2. researcher 汇报
            text_response(
                "现状：工作区为空。\n建议步骤：新建 hello.py，打印一句问候。\n验收标准：文件存在且可直接运行。",
                response_id="r1",
            ),
            # 3. supervisor 委派实现
            tool_call_response(
                "coder",
                {"input": "在工作区新建 hello.py，内容为打印 'hello from harness'。"},
                call_id="c2",
            ),
            # 4. coder 调用真实工具写文件
            tool_call_response(
                "write_file",
                {"path": "hello.py", "content": "print('hello from harness')\n"},
                call_id="c3",
            ),
            # 5. coder 汇报
            text_response("产出：hello.py。验证：未开启 shell，需人工运行确认。", response_id="r2"),
            # 6. supervisor 汇总
            text_response(
                "完成。\n- 产出：hello.py\n- 验证：`python hello.py` 应输出 hello from harness\n- 遗留：本次未做代码审查",
                response_id="r3",
            ),
        ]
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    config = HarnessConfig(
        workspace=OUTPUT_DIR / "workspace",
        runs_dir=OUTPUT_DIR / "runs",
        tracing="local",
    )
    harness = Harness(config, model=build_model())
    print("=== 实时进度（stderr）===", file=sys.stderr)
    outcome = harness.run_sync(
        "在工作区创建一个能打印问候语的 Python 脚本",
        on_event=ConsoleReporter(),
    )
    print(file=sys.stderr)

    print(outcome.render(verbose=True))
    print()
    print("写入的文件内容：")
    print((OUTPUT_DIR / "workspace" / "hello.py").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
