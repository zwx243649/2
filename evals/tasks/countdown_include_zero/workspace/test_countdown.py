"""Tests for countdown.py."""

import countdown


def test_counts_down_to_one():
    assert countdown.countdown(3) == [3, 2, 1]


def test_negative_start():
    assert countdown.countdown(-2) == [-2, -1]
