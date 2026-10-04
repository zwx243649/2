"""Hidden tests for flags.py."""

import pytest

import flags


def test_on_and_off_aliases_are_case_insensitive():
    assert flags.parse_bool("ON") is True
    assert flags.parse_bool("off") is False


def test_numeric_aliases():
    assert flags.parse_bool("1") is True
    assert flags.parse_bool("0") is False


def test_unknown_value_is_rejected():
    with pytest.raises(ValueError):
        flags.parse_bool("maybe")
