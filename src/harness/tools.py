"""工具层：agent 能对工作区做的所有事情都在这里声明。

工具是 harness 的能力边界。模型只能通过这里定义的入口影响外部世界，
所以「新增一个能力」= 「新增一个工具」，而不是改 agent 主循环。
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from pathlib import Path

from agents import FunctionTool, function_tool

from .config import HarnessConfig
from .workspace import Workspace, WorkspaceError

# 注意：这是防手滑，不是安全沙箱。真要跑不可信代码请用容器。
DENY_PATTERNS = (
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "shutdown",
    "reboot",
    "format c:",
    "del /f /s /q c:\\",
    ":(){:|:&};:",
)


def _decode(raw: bytes) -> str:
    """子进程输出按 UTF-8 → 本地编码依次尝试解码。"""
    for encoding in ("utf-8", locale.getpreferredencoding(False) or "utf-8"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _subprocess_env() -> dict[str, str]:
    """让子进程里的 python / pip 指向运行 harness 的那个解释器。

    否则裸 python 会按 PATH 解析到系统解释器：agent 以为自己在验证代码，
    实际跑在另一个环境里；pip install 也会装进系统 Python 而不是本项目。
    """
    env = os.environ.copy()
    scripts_dir = str(Path(sys.executable).parent)
    current = env.get("PATH", "")
    if scripts_dir not in current.split(os.pathsep):
        env["PATH"] = scripts_dir + os.pathsep + current
    return env


def _shell_description() -> str:
    """把平台和 shell 类型写进工具描述，避免模型猜错命令语法。"""
    if os.name == "nt":
        shell_note = (
            "注意：这是 Windows 的 cmd.exe，不是 bash。"
            "没有 tail / grep / which 这类 Unix 命令；"
            "顺序执行用 &&，取上一条退出码用 %errorlevel%，用 python 而不是 python3。"
        )
    else:
        shell_note = "注意：这是 POSIX sh，用 python3 而不是 python。"

    return (
        "在工作区根目录执行一条 shell 命令，返回退出码和输出。\n\n"
        f"{shell_note}\n"
        "python 和 pip 已指向本项目自己的解释器，装依赖请用 python -m pip install。\n\n"
        "适合跑测试、构建、查看目录结构。不要用它做破坏性操作，"
        "也不要修改工作区之外的文件或环境。\n\n"
        "Args:\n"
        '    command: 要执行的命令，例如 "python -m pytest -q"。'
    )


def build_read_tools(workspace: Workspace, *, strict: bool = False) -> list[FunctionTool]:
    """只读工具：所有 worker 都可以拿。"""

    @function_tool(strict_mode=strict)
    def list_files(pattern: str = "**/*") -> str:
        """列出工作区中匹配的文件路径。

        Args:
            pattern: glob 模式，例如 "**/*"（全部）、"src/**/*.py"、"*.md"。
        """
        files = workspace.list_files(pattern)
        if not files:
            return f"没有匹配 {pattern} 的文件。"
        return "\n".join(files)

    @function_tool(strict_mode=strict)
    def read_file(path: str) -> str:
        """读取工作区内一个文本文件的内容。

        Args:
            path: 相对工作区根目录的路径，例如 "src/main.py"。
        """
        return workspace.read_text(path)

    return [list_files, read_file]


def build_write_tools(workspace: Workspace, *, strict: bool = False) -> list[FunctionTool]:
    """写入工具：只给需要产出文件的 worker。"""

    @function_tool(strict_mode=strict)
    def write_file(path: str, content: str) -> str:
        """在工作区内创建或覆盖一个文本文件，父目录会自动创建。

        Args:
            path: 相对工作区根目录的路径，例如 "notes/plan.md"。
            content: 要写入的完整文本内容。
        """
        written = workspace.write_text(path, content)
        return f"已写入 {written}（{len(content)} 字符）"

    return [write_file]


def build_shell_tools(config: HarnessConfig, workspace: Workspace) -> list[FunctionTool]:
    """Shell 工具：默认不注册，需要 HARNESS_ALLOW_SHELL=1 显式打开。"""

    @function_tool(
        strict_mode=config.strict_tools,
        description_override=_shell_description(),
        needs_approval=config.approve_shell,
    )
    def run_command(command: str) -> str:
        """占位 docstring；真实描述见 description_override。"""
        lowered = command.lower()
        if any(pattern in lowered for pattern in DENY_PATTERNS):
            raise WorkspaceError("该命令被 harness 的拒绝列表拦截。")

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace.root),
                capture_output=True,
                timeout=config.shell_timeout,
                check=False,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            raise WorkspaceError(f"命令超时（>{config.shell_timeout}s）：{command}") from None

        stdout = _decode(completed.stdout)[-8000:]
        stderr = _decode(completed.stderr)[-4000:]
        parts = [f"exit_code={completed.returncode}"]
        if stdout.strip():
            parts.append(f"stdout:\n{stdout.rstrip()}")
        if stderr.strip():
            parts.append(f"stderr:\n{stderr.rstrip()}")
        return "\n\n".join(parts)

    return [run_command]
__all__ = [
    "build_read_tools",
    "build_shell_tools",
    "build_write_tools",
]
