"""Hidden tests for password.py."""

import password


def test_whitespace_is_rejected():
    assert password.validate("abcd 123") == ["space"]


def test_multiple_errors_keep_rule_order():
    assert password.validate("!!!!") == ["length", "letter", "digit"]


def test_digit_only_password_misses_a_letter():
    assert password.validate("12345678") == ["letter"]
