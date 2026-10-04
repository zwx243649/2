"""Hidden tests for deepmerge.py."""

import deepmerge


def test_non_dictionary_value_replaces_a_dictionary():
    assert deepmerge.merge({"a": {"x": 1}}, {"a": 2}) == {"a": 2}


def test_inputs_are_not_modified():
    left = {"a": {"x": 1}}
    right = {"a": {"y": 2}}
    result = deepmerge.merge(left, right)
    assert result == {"a": {"x": 1, "y": 2}}
    assert left == {"a": {"x": 1}}
    assert right == {"a": {"y": 2}}


def test_empty_right_returns_a_copy():
    left = {"a": {"x": 1}}
    result = deepmerge.merge(left, {})
    result["a"]["x"] = 9
    assert left == {"a": {"x": 1}}
