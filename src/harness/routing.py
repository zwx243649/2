"""本地任务路由：小任务别绕完整的多智能体流程。

这里不调用模型。先用目标文本和 workspace 体积做保守判断；拿不准就回退到
supervisor，宁可多花一点，也不要让复杂任务走错路径。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .workspace import Workspace

SIMPLE_HINTS = (
    "修复",
    "修好",
    "小改",
    "单文件",
    "off-by-one",
    "bug",
    "pytest",
    "测试",
    "fix",
    "test",
    "写一个",
    "新建",
    "创建",
    "实现一个",
    "修改",
)

COMPLEX_HINTS = (
    "重构",
    "架构",
    "整个项目",
    "全项目",
    "多文件",
    "跨文件",
    "迁移",
    "升级",
    "设计",
    "审查",
    "review",
    "性能",
    "安全",
    "并发",
    "数据模型",
)

# 这些词出现在源码 docstring 里，说明任务虽然小，但契约有明显边界。
# 单 coder 快速路径容易只过可见测试，回退 supervisor 更稳。
CONTRACT_RISK_HINTS = (
    "inclusive",
    "recursive",
    "any iterable",
    "consumed only once",
    "invalid",
    "valueerror",
    "longer than",
    "consecutive whitespace",
    "neither input",
    "never modified",
    "包含 0",
    "递归",
    "任意可迭代",
)

MAX_GOAL_CHARS = 400
MAX_SMALL_FILES = 8
MAX_SMALL_BYTES = 80_000


@dataclass(frozen=True)
class RouteDecision:
    """一次运行的执行路径。"""

    route: str
    reason: str


def _contract_has_risk(workspace: Workspace, files: list[str]) -> bool:
    """扫描非测试源码的 docstring，识别高边界契约。"""
    for relative in files:
        path = workspace.root / relative
        if path.suffix != ".py" or path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue
            text = (ast.get_docstring(node) or "").lower()
            if any(hint in text for hint in CONTRACT_RISK_HINTS):
                return True
    return False


def choose_execution_route(
    goal: str,
    workspace: Workspace,
    *,
    mode: str = "auto",
    has_session: bool = False,
) -> RouteDecision:
    """选择 coder 快速路径或 supervisor 完整编排。"""
    if mode == "off":
        return RouteDecision("supervisor", "routing 已关闭")
    if mode == "always" and not has_session:
        return RouteDecision("coder", "routing=always")
    if has_session:
        return RouteDecision("supervisor", "会话任务保留 supervisor")

    text = (goal or "").strip()
    lowered = text.lower()
    if not text:
        return RouteDecision("supervisor", "空目标")
    if len(text) > MAX_GOAL_CHARS:
        return RouteDecision("supervisor", "目标较长")
    if any(hint in lowered for hint in COMPLEX_HINTS):
        return RouteDecision("supervisor", "命中复杂任务信号")

    files = workspace.list_files("**/*", limit=MAX_SMALL_FILES + 1)
    if len(files) > MAX_SMALL_FILES:
        return RouteDecision("supervisor", "工作区文件较多")

    total_bytes = 0
    for relative in files:
        try:
            total_bytes += (workspace.root / relative).stat().st_size
        except OSError:
            return RouteDecision("supervisor", "无法读取工作区体积")
        if total_bytes > MAX_SMALL_BYTES:
            return RouteDecision("supervisor", "工作区体积较大")

    if _contract_has_risk(workspace, files):
        return RouteDecision("supervisor", "源码契约包含高风险边界")
    if any(hint in lowered for hint in SIMPLE_HINTS):
        return RouteDecision("coder", "小型任务走快速路径")
    return RouteDecision("supervisor", "没有明确的简单任务信号")


__all__ = [
    "COMPLEX_HINTS",
    "CONTRACT_RISK_HINTS",
    "MAX_GOAL_CHARS",
    "MAX_SMALL_BYTES",
    "MAX_SMALL_FILES",
    "RouteDecision",
    "SIMPLE_HINTS",
    "choose_execution_route",
]
