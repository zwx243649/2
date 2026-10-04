"""Tests for frequency.py."""

import frequency


def test_more_frequent_word_comes_first():
    assert frequency.top_k(["a", "a", "b"], 2) == ["a", "b"]


def test_frequency_ties_follow_first_occurrence():
    assert frequency.top_k(["b", "a", "b", "a"], 2) == ["b", "a"]
