"""工作区：把 agent 的文件访问限制在一个目录内。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
}


class WorkspaceError(RuntimeError):
    """工作区内的非法操作（越界、不存在等）。"""


@dataclass
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str, *, must_exist: bool = False) -> Path:
        """把相对路径解析成绝对路径，并确保没有越出工作区。"""
        raw = (path or "").strip()
        if not raw:
            raise WorkspaceError("path 不能为空")

        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.expanduser().resolve()

        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise WorkspaceError(f"路径越界，只允许访问工作区内的文件: {path}")
        if must_exist and not resolved.exists():
            raise WorkspaceError(f"文件不存在: {path}")
        return resolved

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _is_ignored(self, path: Path) -> bool:
        return any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts)

    def list_files(self, pattern: str = "**/*", limit: int = 200) -> list[str]:
        pattern = (pattern or "**/*").strip() or "**/*"
        matches: list[str] = []
        for path in sorted(self.root.glob(pattern)):
            if not path.is_file() or self._is_ignored(path):
                continue
            matches.append(self.rel(path))
            if len(matches) >= limit:
                break
        return matches

    def read_text(self, path: str, max_bytes: int = 200_000) -> str:
        target = self.resolve(path, must_exist=True)
        if target.is_dir():
            raise WorkspaceError(f"{path} 是目录，不是文件。用 list_files 查看内容。")

        raw = target.read_bytes()
        truncated = len(raw) > max_bytes
        body = raw[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            body += f"\n\n[已截断：只显示前 {max_bytes} 字节]"
        return body

    def write_text(self, path: str, content: str) -> str:
        target = self.resolve(path)
        if target.is_dir():
            raise WorkspaceError(f"{path} 是目录，不能写入。")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return self.rel(target)

    def replace_text(self, path: str, old: str, new: str) -> tuple[str, int]:
        """精确替换文件里的一段文本，返回 (相对路径, 替换次数)。

        要求 old 在文件里**唯一出现**。出现了多次就报错而不是猜 —— 猜错
        一次会静默改坏另一处，比报错难查得多。想改多处就带上更多上下文，
        让每一处都能被唯一定位。
        """
        if not old:
            raise WorkspaceError("old 不能为空")

        target = self.resolve(path, must_exist=True)
        if target.is_dir():
            raise WorkspaceError(f"{path} 是目录，不是文件。")

        body = target.read_text(encoding="utf-8")
        occurrences = body.count(old)
        if occurrences == 0:
            raise WorkspaceError(
                f"在 {path} 里找不到要替换的内容。"
                "注意 old 必须逐字符匹配（包括缩进和空行）；"
                "先用 read_file 确认原文。"
            )
        if occurrences > 1:
            raise WorkspaceError(
                f"要替换的内容在 {path} 里出现了 {occurrences} 次，无法确定改哪一处。"
                "请多带几行上下文，让匹配唯一。"
            )

        target.write_text(body.replace(old, new, 1), encoding="utf-8", newline="\n")
        return self.rel(target), 1
