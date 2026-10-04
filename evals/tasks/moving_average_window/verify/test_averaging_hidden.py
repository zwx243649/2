"""Hidden tests for averaging.py."""

import averaging


def test_window_of_one_returns_the_original_values():
    assert averaging.moving_average([2, 4, 6], 1) == [2, 4, 6]


def test_full_length_window_has_one_result():
    assert averaging.moving_average([1, 2, 3, 4], 4) == [2.5]


def test_non_positive_window_returns_empty():
    assert averaging.moving_average([1, 2, 3], 0) == []
