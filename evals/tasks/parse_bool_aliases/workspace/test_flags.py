"""Tests for flags.py."""

import flags


def test_true_literal():
    assert flags.parse_bool("true") is True


def test_false_literal():
    assert flags.parse_bool("false") is False


def test_yes_alias():
    assert flags.parse_bool(" yes ") is True
