"""Tests for flattening.py."""

import flattening


def test_mixed_scalars_and_nested_lists():
    assert flattening.flatten([1, [2, 3], 4]) == [1, 2, 3, 4]


def test_empty_input():
    assert flattening.flatten([]) == []
