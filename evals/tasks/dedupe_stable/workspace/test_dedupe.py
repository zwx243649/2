"""Tests for dedupe.py."""

import dedupe


def test_removes_duplicates():
    assert len(dedupe.dedupe([1, 2, 1, 3])) == 3


def test_keeps_every_distinct_value():
    assert sorted(dedupe.dedupe(["b", "a", "b"])) == ["a", "b"]
