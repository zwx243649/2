"""Tests for intervals.py."""

import intervals


def test_overlapping_intervals_merge():
    assert intervals.merge([(1, 4), (3, 6)]) == [(1, 6)]


def test_touching_intervals_merge():
    assert intervals.merge([(1, 3), (3, 5)]) == [(1, 5)]
