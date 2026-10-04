"""Tests for deepmerge.py."""

import deepmerge


def test_top_level_values_are_merged():
    assert deepmerge.merge({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {
        "a": 1,
        "b": 3,
        "c": 4,
    }


def test_nested_dictionaries_are_merged_recursively():
    assert deepmerge.merge(
        {"config": {"host": "localhost", "port": 80}},
        {"config": {"port": 8080}},
    ) == {"config": {"host": "localhost", "port": 8080}}
