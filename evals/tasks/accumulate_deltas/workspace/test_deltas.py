"""Tests for deltas.py."""

import deltas


def test_values_are_updated():
    assert deltas.apply_deltas([10, 20], [1, -2]) == [11, 18]


def test_input_list_is_not_modified():
    values = [10, 20]
    deltas.apply_deltas(values, [1, 2])
    assert values == [10, 20]
