"""Tests for grouping.py."""

import grouping


def test_groups_values_by_key():
    assert grouping.group_by(["a1", "b1", "a2"], lambda value: value[0]) == {
        "a": ["a1", "a2"],
        "b": ["b1"],
    }


def test_keys_follow_first_occurrence():
    result = grouping.group_by(["b1", "a1", "b2"], lambda value: value[0])
    assert list(result) == ["b", "a"]
