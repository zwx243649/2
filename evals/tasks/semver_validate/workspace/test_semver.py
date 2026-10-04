"""Tests for semver.py."""

import pytest

import semver


def test_plain_version():
    assert semver.parse("1.2.3") == (1, 2, 3)


def test_zero_components():
    assert semver.parse("0.0.0") == (0, 0, 0)


def test_suffix_is_not_allowed():
    with pytest.raises(ValueError):
        semver.parse("1.2.3-beta")
