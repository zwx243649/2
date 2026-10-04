"""Tests for pathjoin.py."""

import pathjoin


def test_simple_segments():
    assert pathjoin.join_parts(["src", "pkg", "mod.py"]) == "src/pkg/mod.py"


def test_empty_and_current_directory_segments_are_skipped():
    assert pathjoin.join_parts(["src", "", ".", "mod.py"]) == "src/mod.py"
