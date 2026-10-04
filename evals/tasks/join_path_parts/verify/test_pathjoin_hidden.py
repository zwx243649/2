"""Hidden tests for pathjoin.py."""

import pytest

import pathjoin


def test_segment_slashes_are_trimmed():
    assert pathjoin.join_parts(["/src/", "/pkg/"]) == "src/pkg"


def test_parent_segment_is_rejected():
    with pytest.raises(ValueError):
        pathjoin.join_parts(["src", "..", "secret"])


def test_no_segments_returns_empty_string():
    assert pathjoin.join_parts(["", "."]) == ""
