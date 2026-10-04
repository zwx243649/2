"""Hidden tests for flattening.py."""

import flattening


def test_deep_nesting_is_flattened():
    assert flattening.flatten([1, [2, [3, [4]], 5]]) == [1, 2, 3, 4, 5]


def test_tuples_are_traversed_too():
    assert flattening.flatten((1, (2, 3), [4])) == [1, 2, 3, 4]


def test_non_sequence_values_are_kept():
    assert flattening.flatten([1, "ab", None]) == [1, "ab", None]
