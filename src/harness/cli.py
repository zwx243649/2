"""命令行入口：python -m harness "你的任务"。"""

from __future__ import annotations

import argparse
import sys

from .config import TRACING_MODES, HarnessConfig
from .progress import ConsoleReporter
from .runner import Harness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Supervisor + worker 多智能体 harness（基于 openai-agents）",
    )
    parser.add_argument("goal", nargs="?", help="要完成的任务；省略时从 stdin 读取")
    parser.add_argument("--workspace", help="工作区目录（agent 只能在这里读写）")
    parser.add_argument("--model", help="模型名，例如 gpt-4.1-mini / deepseek-chat")
    parser.add_argument(
        "--base-url",
        dest="base_url",
        help="OpenAI 兼容端点；设置后自动切到 Chat Completions",
    )
    parser.add_argument("--max-turns", dest="max_turns", type=int, help="supervisor 最大轮数")
    parser.add_argument(
        "--allow-shell",
        dest="allow_shell",
        action="store_const",
        const=True,
        default=None,
        help="允许 worker 执行 shell 命令（默认关闭）",
    )
    parser.add_argument("--tracing", choices=TRACING_MODES, help="追踪模式")
    parser.add_argument(
        "--no-artifacts",
        dest="save_artifacts",
        action="store_const",
        const=False,
        default=None,
        help="不写 runs/ 目录",
    )
    parser.add_argument("--env-file", dest="env_file", default=".env", help=".env 路径")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="只打印解析后的配置和工具装配，不调用模型",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="打印内部 span 时间线")
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="不输出实时进度，只在结束时打印报告",
    )
    return parser


def _read_stdin_goal() -> str:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
    except ValueError:
        return ""
    return sys.stdin.read().strip()


def _describe(harness: Harness) -> str:
    config = harness.config
    lines = [
        "配置",
        f"  model      : {config.model}",
        f"  base_url   : {config.base_url or '(OpenAI 官方 Responses API)'}",
        f"  api_key    : {'已设置' if config.resolved_api_key else '未设置'}",
        f"  workspace  : {config.workspace}",
        f"  runs_dir   : {config.runs_dir}",
        f"  tracing    : {config.tracing}",
        f"  allow_shell: {config.allow_shell}",
        f"  env_file   : {config.env_file or '(未使用)'}",
        "",
        "supervisor 可委派的成员",
    ]
    for tool in harness.supervisor.tools:
        lines.append(f"  - {tool.name}")
    lines.append("")
    lines.append("每个成员拥有的工具")
    for worker in harness.workers:
        names = ", ".join(tool.name for tool in worker.tools) or "(无)"
        lines.append(f"  - {worker.name}: {names}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:  # 避免 Windows 控制台把中文输出成乱码
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    goal = (args.goal or "").strip() or _read_stdin_goal()

    override_keys = (
        "model",
        "base_url",
        "workspace",
        "max_turns",
        "allow_shell",
        "tracing",
        "save_artifacts",
    )
    overrides = {key: getattr(args, key) for key in override_keys}

    try:
        config = HarnessConfig.from_env(env_file=args.env_file, **overrides)
    except Exception as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    try:
        harness = Harness(config)
    except Exception as exc:
        print(f"初始化失败: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(_describe(harness))
        return 0

    if not goal:
        parser.print_help()
        return 2

    if config.resolved_api_key is None and config.base_url is None:
        print(
            "还没有配置模型凭据。二选一：\n"
            "  1) 复制 .env.example 为 .env，填 HARNESS_API_KEY\n"
            "  2) 设置 HARNESS_BASE_URL 指向你的 OpenAI 兼容端点"
            "（如本地 Ollama: http://localhost:11434/v1）\n"
            "也可以先跑 python examples/offline_demo.py 看流程。",
            file=sys.stderr,
        )
        return 2

    try:
        # 进度走 stderr，最终报告走 stdout，方便 `> result.txt` 重定向
        reporter = None if args.quiet else ConsoleReporter()
        outcome = harness.run_sync(goal, on_event=reporter)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"运行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(outcome.render(verbose=args.verbose))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
