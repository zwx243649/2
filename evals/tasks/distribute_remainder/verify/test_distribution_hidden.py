"""Hidden tests for distribution.py."""

import pytest

import distribution


def test_more_buckets_than_values():
    assert distribution.split_evenly([1, 2], 4) == [[1], [2], [], []]


def test_empty_input_returns_empty_buckets():
    assert distribution.split_evenly([], 3) == [[], [], []]


def test_non_positive_bucket_count_is_rejected():
    with pytest.raises(ValueError):
        distribution.split_evenly([1], 0)
