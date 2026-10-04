"""Hidden tests for textutils.py."""

import textutils


def test_long_word_is_cut_at_the_limit():
    assert textutils.truncate("supercalifragilistic", 6) == "superc..."


def test_trailing_spaces_do_not_leak_into_the_result():
    assert textutils.truncate("one two three", 8) == "one two..."
