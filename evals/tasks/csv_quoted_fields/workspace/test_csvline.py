"""Tests for csvline.py."""

import csvline


def test_plain_fields():
    assert csvline.parse_line("a,b,c") == ["a", "b", "c"]


def test_quoted_comma_stays_in_one_field():
    assert csvline.parse_line('a,"b,c",d') == ["a", "b,c", "d"]
