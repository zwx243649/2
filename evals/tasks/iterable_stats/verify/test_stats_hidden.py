"""Hidden tests for stats.py."""

import pytest

import mathutils
import stats


def test_mean_accepts_a_generator():
    assert stats.mean(number for number in [2, 4, 6]) == 4


def test_total_accepts_a_generator():
    assert mathutils.total(number for number in [1, 2, 3]) == 6


def test_empty_generator_raises_value_error():
    with pytest.raises(ValueError):
        stats.mean(number for number in [])
