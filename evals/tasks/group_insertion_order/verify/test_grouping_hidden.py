"""Hidden tests for grouping.py."""

import grouping


def test_empty_input():
    assert grouping.group_by([], lambda value: value) == {}


def test_duplicate_values_stay_in_source_order():
    assert grouping.group_by([3, 1, 3, 2], lambda value: value % 2) == {
        1: [3, 1, 3],
        0: [2],
    }
