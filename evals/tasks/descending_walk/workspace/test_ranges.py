"""Tests for ranges.py."""

import ranges


def test_ascending_covers_both_ends():
    assert ranges.walk(1, 4) == [1, 2, 3, 4]


def test_single_value():
    assert ranges.walk(7, 7) == [7]
