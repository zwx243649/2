from __future__ import annotations

from harness.routing import choose_execution_route
from harness.workspace import Workspace


def small_workspace(tmp_path) -> Workspace:
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("a.py", "value = 1\n")
    return workspace


def test_simple_small_task_routes_to_coder(tmp_path):
    decision = choose_execution_route(
        "修复 a.py 的 pytest 失败", small_workspace(tmp_path), mode="auto"
    )

    assert decision.route == "coder"


def test_complex_task_keeps_supervisor(tmp_path):
    decision = choose_execution_route(
        "重构整个项目并升级数据模型", small_workspace(tmp_path), mode="auto"
    )

    assert decision.route == "supervisor"


def test_large_workspace_keeps_supervisor(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    for index in range(10):
        workspace.write_text(f"mod_{index}.py", "value = 1\n")

    decision = choose_execution_route(
        "修复 pytest 失败", workspace, mode="auto"
    )

    assert decision.route == "supervisor"


def test_edge_contract_in_docstring_keeps_supervisor(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text(
        "a.py",
        'def countdown(start):\n    """Count down to zero, inclusive."""\n'
        "    return list(range(start, 0, -1))\n",
    )

    decision = choose_execution_route(
        "修复 pytest 失败", workspace, mode="auto"
    )

    assert decision.route == "supervisor"


def test_session_task_keeps_supervisor(tmp_path):
    decision = choose_execution_route(
        "修复 a.py",
        small_workspace(tmp_path),
        mode="auto",
        has_session=True,
    )

    assert decision.route == "supervisor"


def test_routing_can_be_forced_off_or_always(tmp_path):
    workspace = small_workspace(tmp_path)

    assert choose_execution_route("修复", workspace, mode="off").route == "supervisor"
    assert choose_execution_route("重构整个项目", workspace, mode="always").route == "coder"
