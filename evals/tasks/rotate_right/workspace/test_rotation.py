"""Tests for rotation.py."""

import rotation


def test_rotate_by_one():
    assert rotation.rotate_right([1, 2, 3], 1) == [3, 1, 2]


def test_empty_sequence():
    assert rotation.rotate_right([], 3) == []
