"""Tests for searching.py."""

import searching


def test_single_target_is_found():
    assert searching.find_last([1, 3, 5], 3) == 1


def test_last_duplicate_is_returned():
    assert searching.find_last([1, 2, 2, 2, 4], 2) == 3
