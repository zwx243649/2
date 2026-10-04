"""Tests for distribution.py."""

import distribution


def test_even_split():
    assert distribution.split_evenly([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_remainder_goes_to_earlier_buckets():
    assert distribution.split_evenly([1, 2, 3], 2) == [[1, 2], [3]]
