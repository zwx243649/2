"""Hidden tests for frequency.py."""

import frequency


def test_k_larger_than_unique_count_returns_everything():
    assert frequency.top_k(["b", "a", "b"], 10) == ["b", "a"]


def test_non_positive_k_returns_empty_list():
    assert frequency.top_k(["a", "b"], 0) == []


def test_three_way_tie_keeps_source_order():
    assert frequency.top_k(["c", "a", "b"], 3) == ["c", "a", "b"]
