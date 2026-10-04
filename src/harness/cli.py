"""命令行入口：python -m harness "你的任务"。"""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Any

from .cancel import CancelToken
from .config import ROUTING_MODES, TRACING_MODES, HarnessConfig
from .console import force_utf8_stdout
from .server import DEFAULT_PORT
from .server import serve as serve_runs
from .sessions import InvalidSessionId, validate_session_id

# 刻意不在模块顶层 import .runner / .progress：它们会拉起整个 agents SDK，
# 实测 6 秒。而 --help / --pending / --list-sessions / --serve 都用不到模型。

NO_CREDENTIALS_HINT = (
    "还没有配置模型凭据。二选一：\n"
    "  1) 复制 .env.example 为 .env，填 HARNESS_API_KEY\n"
    "  2) 设置 HARNESS_BASE_URL 指向你的 OpenAI 兼容端点"
    "（如本地 Ollama: http://localhost:11434/v1）\n"
    "也可以先跑 python examples/offline_demo.py 看流程。"
)


def _list_sessions(config: HarnessConfig) -> int:
    from .runs_index import list_sessions

    sessions = list_sessions(config.runs_dir)
    if not sessions:
        print("还没有会话。用 --session <名字> 跑一次任务就会创建。")
        return 0

    print(f"{'会话':<22} {'运行':>4} {'tokens':>9}  {'最近一次':<16} 标题")
    for item in sessions:
        title = item.title if len(item.title) <= 36 else item.title[:36] + "…"
        print(
            f"{item.session_id:<22} {item.run_count:>4} {item.total_tokens:>9}  "
            f"{item.last_run:<16} {title}"
        )
    return 0


def _list_pending(config: HarnessConfig) -> int:
    from .runs_index import list_pending
    from .testresults import describe

    items = list_pending(config.runs_dir)
    if not items:
        print("没有等待批准的工具调用。")
        return 0

    for item in items:
        label = "等批准" if item.status == "paused" else "已停止"
        print(f"{item.run_id}  [{label}]  {item.display_time}  {item.goal[:44]}")
        if item.test_result:
            # 放行之前先看到「上次是多少」，才判断得出这次有没有变糟
            print(f"    上次测试: {describe(item.test_result)}")
        for call in item.pending:
            print(f"    待批准 [{call.get('tool')}] {call.get('arguments')}")
        if item.status == "paused":
            print(f"    批准: python -m harness --approve {item.run_id}")
            print(f"    拒绝: python -m harness --reject {item.run_id}")
        else:
            print(f"    继续: python -m harness --resume {item.run_id}")
        print(f"    放弃: python -m harness --discard {item.run_id}")
    return 0


def _discard(config: HarnessConfig, run_id: str) -> int:
    """放弃一次待处理的工作。不调用模型，所以不需要凭据。"""
    from .runs_index import RunNotFound, discard_run

    try:
        discard_run(config.runs_dir, run_id)
    except (RunNotFound, FileNotFoundError) as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"删除状态失败: {exc}", file=sys.stderr)
        return 1

    print(f"已放弃 {run_id}，它不再出现在待处理列表里。")
    return 0


def _run_resume(config: HarnessConfig, run_id: str, approve: bool, quiet: bool) -> int:
    from .runs_index import load_graph_config
    from .progress import ConsoleReporter
    from .runner import Harness

    try:
        stored = load_graph_config(config.runs_dir, run_id)
    except Exception as exc:
        print(f"读取运行记录失败: {exc}", file=sys.stderr)
        return 2

    if stored:
        # 工具配置不跟着一起恢复的话，待执行的工具在新建的图里不存在，
        # 会永远卡在同一个暂停点。
        config = config.with_overrides(**stored)
        print(f"已恢复该次运行的配置: {stored}", file=sys.stderr)

    try:
        harness = Harness(config)
    except Exception as exc:
        print(f"初始化失败: {exc}", file=sys.stderr)
        return 2

    try:
        outcome = harness.resume_sync(
            run_id, approve=approve, on_event=None if quiet else ConsoleReporter()
        )
    except FileNotFoundError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"续跑失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        harness.close()

    print(outcome.render())
    return 0


def _has_credentials(config: HarnessConfig) -> bool:
    return config.resolved_api_key is not None or config.base_url is not None


def _sigint_handler(token: CancelToken, presses: dict[str, int]):
    """把 Ctrl+C 转成取消信号。

    第一次按：设置取消信号，让运行自己收尾（状态会留下来，之后能 --resume）。
    第二次按：恢复默认行为并抛 KeyboardInterrupt，用于运行卡死时强退。

    单独抽出来是为了能确定性地测试 —— 真实的控制台事件没法在自动化里可靠地造。
    """

    def handler(signum: int, frame: object) -> None:
        presses["count"] += 1
        if presses["count"] == 1:
            token.cancel()
            print("\n正在停止…（再按一次 Ctrl+C 强制退出）", file=sys.stderr)
        else:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            raise KeyboardInterrupt

    return handler


def _run_with_cancel(
    harness: Any, goal: str, session_id: str | None, quiet: bool
) -> Any:
    """跑任务，把 Ctrl+C 变成协作式取消。

    直接让 KeyboardInterrupt 冒出去的话，这次运行攒下的状态会一起丢掉。
    """
    token = CancelToken()
    handler = _sigint_handler(token, {"count": 0})
    from .progress import ConsoleReporter

    previous = signal.signal(signal.SIGINT, handler)
    try:
        return harness.run_sync(
            goal,
            session_id=session_id,
            on_event=None if quiet else ConsoleReporter(),
            cancel_token=token,
        )
    finally:
        signal.signal(signal.SIGINT, previous)


def _serve(config: HarnessConfig, port: int) -> int:
    try:
        httpd = serve_runs(config, port=port)
    except OSError as exc:
        print(f"启动失败（端口被占用？）: {exc}", file=sys.stderr)
        return 1

    host, bound_port = httpd.server_address[:2]
    display_host = "localhost" if host in {"127.0.0.1", "::1"} else host
    print(f"运行控制台：http://{display_host}:{bound_port}")
    print(f"数据目录　：{config.runs_dir}")
    print("按 Ctrl+C 停止。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


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
        "--session-items",
        dest="session_item_limit",
        type=int,
        help="会话最多传给模型的条目数（默认 80，0 表示不折叠）",
    )
    parser.add_argument(
        "--model-timeout",
        dest="model_timeout",
        type=float,
        help="单次模型请求的空闲超时秒数（默认 120）",
    )
    parser.add_argument(
        "--model-retries",
        dest="model_max_retries",
        type=int,
        help="模型请求失败后的重试次数（默认 1）",
    )
    parser.add_argument(
        "--routing",
        dest="routing_mode",
        choices=ROUTING_MODES,
        help="任务路由：auto（默认）/ off / always",
    )
    parser.add_argument(
        "--fast-turns",
        dest="fast_path_max_turns",
        type=int,
        help="快速路径最大轮数（默认 8）",
    )
    parser.add_argument(
        "--no-dedupe",
        dest="dedupe_tools",
        action="store_const",
        const=False,
        default=None,
        help="关闭重复读取折叠",
    )
    parser.add_argument(
        "--dedupe-reads",
        dest="dedupe_tools",
        action="store_const",
        const=True,
        default=None,
        help="实验性开启重复读取折叠（默认关闭）",
    )
    parser.add_argument(
        "--tool-output-chars",
        dest="tool_output_chars",
        type=int,
        help="单次文件读取最多返回的字符数（默认 24000）",
    )
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
        "--serve",
        action="store_true",
        help="启动运行控制台（查看历史、发起/停止/批准任务）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"运行控制台的端口（默认 {DEFAULT_PORT}）",
    )
    parser.add_argument(
        "--session",
        help="在指定会话里运行，复用该会话之前的历史（多轮追问）",
    )
    parser.add_argument(
        "--list-sessions",
        dest="list_sessions",
        action="store_true",
        help="列出所有会话后退出",
    )
    parser.add_argument(
        "--pending",
        action="store_true",
        help="列出正在等待批准的工具调用",
    )
    parser.add_argument(
        "--approve",
        metavar="RUN_ID",
        help="批准某次暂停运行里的待执行工具，并继续运行",
    )
    parser.add_argument(
        "--reject",
        metavar="RUN_ID",
        help="拒绝该工具调用，并继续运行",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="继续一次被停止（或已批准）的运行",
    )
    parser.add_argument(
        "--discard",
        metavar="RUN_ID",
        help="放弃一次待处理/被停止的运行（只删状态标记，不调用模型、不花钱）",
    )
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


def _describe(harness: Any) -> str:
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
        f"  session_items: {config.session_item_limit or '(不折叠)'}",
        f"  model_timeout: {config.model_timeout}s / retries {config.model_max_retries}",
        f"  routing    : {config.routing_mode} / fast turns {config.fast_path_max_turns}",
        f"  dedupe read: {config.dedupe_tools}",
        f"  tool output: {config.tool_output_chars} chars",
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
    force_utf8_stdout()

    parser = build_parser()
    args = parser.parse_args(argv)

    goal = (args.goal or "").strip() or _read_stdin_goal()

    override_keys = (
        "model",
        "base_url",
        "workspace",
        "max_turns",
        "session_item_limit",
        "model_timeout",
        "model_max_retries",
        "routing_mode",
        "fast_path_max_turns",
        "dedupe_tools",
        "tool_output_chars",
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

    if args.serve:
        return _serve(config, args.port)

    if args.list_sessions:
        return _list_sessions(config)

    if args.pending:
        return _list_pending(config)

    action = args.approve or args.reject
    if action:
        if not _has_credentials(config):
            print(NO_CREDENTIALS_HINT, file=sys.stderr)
            return 2
        return _run_resume(
            config, action, approve=bool(args.approve), quiet=args.quiet
        )

    if args.resume:
        if not _has_credentials(config):
            print(NO_CREDENTIALS_HINT, file=sys.stderr)
            return 2
        return _run_resume(config, args.resume, approve=True, quiet=args.quiet)

    if args.discard:
        # 不需要模型，所以放在凭据检查之前
        return _discard(config, args.discard)

    if args.session:
        try:
            validate_session_id(args.session)
        except InvalidSessionId as exc:
            print(f"会话名不合法: {exc}", file=sys.stderr)
            return 2

    try:
        from .runner import Harness

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

    if not _has_credentials(config):
        print(NO_CREDENTIALS_HINT, file=sys.stderr)
        return 2

    try:
        # 进度走 stderr，最终报告走 stdout，方便 `> result.txt` 重定向
        outcome = _run_with_cancel(harness, goal, args.session, args.quiet)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"运行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        harness.close()

    print(outcome.render(verbose=args.verbose))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
