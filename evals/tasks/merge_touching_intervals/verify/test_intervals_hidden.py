"""Hidden tests for intervals.py."""

import intervals


def test_unsorted_intervals_are_sorted_before_merging():
    assert intervals.merge([(8, 10), (1, 3), (2, 5)]) == [(1, 5), (8, 10)]


def test_nested_interval_does_not_shrink_the_result():
    assert intervals.merge([(1, 10), (3, 4)]) == [(1, 10)]


def test_disjoint_intervals_are_preserved():
    assert intervals.merge([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]
