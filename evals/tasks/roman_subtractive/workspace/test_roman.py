"""Tests for roman.py."""

import roman


def test_repeated_symbols_are_added():
    assert roman.roman_to_int("III") == 3


def test_subtractive_pair():
    assert roman.roman_to_int("IV") == 4
