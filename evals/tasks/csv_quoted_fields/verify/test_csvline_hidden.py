"""Hidden tests for csvline.py."""

import csvline


def test_escaped_quote_inside_a_field():
    assert csvline.parse_line('"say ""hi""",ok') == ['say "hi"', "ok"]


def test_empty_fields_are_preserved():
    assert csvline.parse_line("a,,c") == ["a", "", "c"]


def test_all_fields_can_be_quoted():
    assert csvline.parse_line('"a","b"') == ["a", "b"]
