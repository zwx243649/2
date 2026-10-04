"""Tests for wrapping.py."""

import wrapping


def test_normal_wrapping():
    assert wrapping.wrap("one two three", 7) == ["one two", "three"]


def test_long_words_are_not_split():
    assert wrapping.wrap("abcdefgh", 3) == ["abcdefgh"]
