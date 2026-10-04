"""Hidden tests for roman.py."""

import pytest

import roman


def test_larger_subtractive_number():
    assert roman.roman_to_int("MCMXCIV") == 1994


def test_mixed_additive_and_subtractive_pairs():
    assert roman.roman_to_int("CDXLIX") == 449


def test_invalid_symbols_are_rejected():
    with pytest.raises(ValueError):
        roman.roman_to_int("ABC")
