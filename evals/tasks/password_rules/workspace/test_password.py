"""Tests for password.py."""

import password


def test_valid_password():
    assert password.validate("abcd1234") == []


def test_missing_digit():
    assert password.validate("abcdefgh") == ["digit"]
