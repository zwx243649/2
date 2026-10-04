"""Hidden tests for running.py."""

import running


def test_negative_values_work():
    assert running.running_max([-5, -2, -9, -1]) == [-5, -2, -2, -1]


def test_plateau_keeps_the_previous_maximum():
    assert running.running_max([4, 4, 3, 5]) == [4, 4, 4, 5]
