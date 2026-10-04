"""Tests for averaging.py."""

import averaging


def test_two_value_window():
    assert averaging.moving_average([1, 2, 3], 2) == [1.5, 2.5]


def test_window_larger_than_input_returns_empty():
    assert averaging.moving_average([1, 2], 3) == []
