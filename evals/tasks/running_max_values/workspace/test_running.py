"""Tests for running.py."""

import running


def test_running_maximum_updates_after_a_new_high():
    assert running.running_max([1, 3, 2]) == [1, 3, 3]


def test_empty_input():
    assert running.running_max([]) == []
