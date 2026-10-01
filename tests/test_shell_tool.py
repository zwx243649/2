"""shell 工具的两条关键约束。

都来自一次真实的运行审计：
  1. 裸 python 按 PATH 解析到了系统解释器，agent 以为在验证代码，
     实际跑在另一个 Python 里，还把 pytest 装进了系统环境。
  2. 工具描述没说这是什么 shell，模型先试了 tail（Unix 命令）才改用 Windows 写法。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from harness.config import HarnessConfig
from harness.tools import _shell_description, _subprocess_env, build_shell_tools
from harness.workspace import Workspace


def _shell_tool(tmp_path):
    config = HarnessConfig(workspace=tmp_path / "ws", allow_shell=True)
    tools = build_shell_tools(config, Workspace(config.workspace))
    assert len(tools) == 1
    return tools[0]


def test_subprocess_env_puts_harness_interpreter_first():
    env = _subprocess_env()

    first_on_path = Path(env["PATH"].split(os.pathsep)[0])

    assert first_on_path == Path(sys.executable).parent


def test_python_in_child_resolves_to_harness_interpreter():
    """真正跑一次，确认 python 就是运行 harness 的那个解释器。"""
    completed = subprocess.run(
        'python -c "import sys; print(sys.executable)"',
        shell=True,
        capture_output=True,
        env=_subprocess_env(),
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    resolved = Path(completed.stdout.decode("utf-8", "replace").strip()).resolve()
    assert resolved == Path(sys.executable).resolve()


def test_shell_description_names_the_actual_shell():
    description = _shell_description()

    if os.name == "nt":
        assert "cmd.exe" in description
        assert "tail" in description  # 明确提醒没有 Unix 命令
        assert "%errorlevel%" in description
    else:
        assert "sh" in description


def test_shell_description_warns_against_touching_the_machine(tmp_path):
    tool = _shell_tool(tmp_path)

    assert "python -m pip install" in tool.description
    assert "工作区之外" in tool.description
