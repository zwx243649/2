"""Hidden tests for wrapping.py."""

import pytest

import wrapping


def test_long_word_and_short_words_stay_together_on_separate_lines():
    assert wrapping.wrap("a abcdefgh b", 4) == ["a", "abcdefgh", "b"]


def test_repeated_spaces_are_collapsed():
    assert wrapping.wrap("one    two", 7) == ["one two"]


def test_non_positive_width_is_rejected():
    with pytest.raises(ValueError):
        wrapping.wrap("text", 0)
