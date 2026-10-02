"""Tests for chunks.py."""

import chunks


def test_exact_multiple():
    assert chunks.chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_size_larger_than_input():
    assert chunks.chunk([1, 2], 5) == [[1, 2]]
