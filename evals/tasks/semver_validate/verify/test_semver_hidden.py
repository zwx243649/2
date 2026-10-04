"""Hidden tests for semver.py."""

import pytest

import semver


def test_leading_zero_is_rejected():
    with pytest.raises(ValueError):
        semver.parse("01.2.3")


def test_suffix_is_rejected():
    with pytest.raises(ValueError):
        semver.parse("1.2.3-beta")


def test_surrounding_whitespace_is_rejected():
    with pytest.raises(ValueError):
        semver.parse(" 1.2.3 ")
