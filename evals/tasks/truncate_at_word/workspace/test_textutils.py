"""Tests for textutils.py."""

import textutils


def test_short_text_is_unchanged():
    assert textutils.truncate("hello", 10) == "hello"


def test_breaks_at_the_last_complete_word():
    assert textutils.truncate("hello world", 8) == "hello..."
