"""Hidden tests for searching.py."""

import searching


def test_missing_target_returns_minus_one():
    assert searching.find_last([1, 3, 5], 4) == -1


def test_target_before_the_first_value():
    assert searching.find_last([2, 4, 6], 1) == -1


def test_duplicate_target_at_the_end():
    assert searching.find_last([1, 3, 3, 3], 3) == 3
