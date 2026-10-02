"""Tests for clamping.py."""

import clamping


def test_value_inside_range_is_unchanged():
    assert clamping.clamp(5, 0, 10) == 5


def test_value_above_range_is_capped():
    assert clamping.clamp(99, 0, 10) == 10
