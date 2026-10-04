"""Hidden tests for deltas.py."""

import pytest

import deltas


def test_empty_sequences_are_allowed():
    assert deltas.apply_deltas([], []) == []


def test_too_many_deltas_are_rejected():
    with pytest.raises(ValueError):
        deltas.apply_deltas([1], [2, 3])


def test_too_few_deltas_are_rejected():
    with pytest.raises(ValueError):
        deltas.apply_deltas([1, 2], [3])
