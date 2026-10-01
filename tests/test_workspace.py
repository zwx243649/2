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
