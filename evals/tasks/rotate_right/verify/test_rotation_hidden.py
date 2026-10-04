"""Hidden tests for rotation.py."""

import rotation


def test_large_step_count_wraps_around():
    assert rotation.rotate_right([1, 2, 3], 7) == [3, 1, 2]


def test_negative_step_rotates_left():
    assert rotation.rotate_right([1, 2, 3, 4], -1) == [2, 3, 4, 1]


def test_input_is_not_modified():
    values = [1, 2, 3]
    rotation.rotate_right(values, 2)
    assert values == [1, 2, 3]
