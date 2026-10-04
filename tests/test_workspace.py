from __future__ import annotations

import pytest

from harness.workspace import Workspace, WorkspaceError


def test_write_then_read_roundtrip(tmp_path):
    workspace = Workspace(tmp_path / "ws")

    assert workspace.write_text("notes/plan.md", "hello") == "notes/plan.md"
    assert workspace.read_text("notes/plan.md") == "hello"
    assert workspace.list_files() == ["notes/plan.md"]


def test_path_escape_is_rejected(tmp_path):
    workspace = Workspace(tmp_path / "ws")

    for bad in ("../outside.txt", "notes/../../outside.txt"):
        with pytest.raises(WorkspaceError):
            workspace.write_text(bad, "nope")


def test_absolute_path_outside_root_is_rejected(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    outside = tmp_path / "outside.txt"

    with pytest.raises(WorkspaceError):
        workspace.write_text(str(outside), "nope")


def test_list_files_skips_noise_directories(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("keep.txt", "a")
    workspace.write_text(".venv/lib/site.py", "b")
    workspace.write_text("__pycache__/x.pyc", "c")

    assert workspace.list_files() == ["keep.txt"]


def test_reading_missing_file_reports_clearly(tmp_path):
    workspace = Workspace(tmp_path / "ws")

    with pytest.raises(WorkspaceError, match="不存在"):
        workspace.read_text("nope.txt")


def test_read_text_honors_a_character_budget(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("big.txt", "x" * 500)

    body = workspace.read_text("big.txt", max_chars=120)

    assert body.startswith("x" * 120)
    assert "已截断" in body


# ---- 精确替换（edit_file 的底座）----


def test_replace_text_swaps_a_unique_snippet(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("a.py", "import foo\nprint(1)\n")

    rel, count = workspace.replace_text("a.py", "import foo", "from pkg import foo")

    assert (rel, count) == ("a.py", 1)
    assert workspace.read_text("a.py") == "from pkg import foo\nprint(1)\n"


def test_replace_text_rejects_a_missing_snippet(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("a.py", "print(1)\n")

    with pytest.raises(WorkspaceError, match="找不到"):
        workspace.replace_text("a.py", "import foo", "import bar")


def test_replace_text_refuses_ambiguous_matches(tmp_path):
    """出现了多次就报错，不猜 —— 猜错会静默改坏另一处。"""
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("a.py", "x = 1\nx = 1\n")

    with pytest.raises(WorkspaceError, match="出现了 2 次"):
        workspace.replace_text("a.py", "x = 1", "x = 2")

    assert workspace.read_text("a.py") == "x = 1\nx = 1\n"  # 原文没被改


def test_replace_text_needs_a_non_empty_old(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_text("a.py", "x\n")

    with pytest.raises(WorkspaceError, match="不能为空"):
        workspace.replace_text("a.py", "", "y")


def test_replace_text_cannot_escape_the_workspace(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n", encoding="utf-8")

    with pytest.raises(WorkspaceError):
        workspace.replace_text("../outside.py", "secret", "leaked")
