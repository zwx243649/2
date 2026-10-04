"""Tests for stats.py."""

import pytest

import stats


def test_mean_of_a_list():
    assert stats.mean([2, 4, 6]) == 4


def test_empty_input_raises_value_error():
    with pytest.raises(ValueError):
        stats.mean([])
