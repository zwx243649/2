"""Hidden tests for slugify.py."""

import slugify


def test_runs_of_punctuation_collapse():
    assert slugify.slugify("Python --- Async!!! IO") == "python-async-io"


def test_leading_and_trailing_separators_are_trimmed():
    assert slugify.slugify("  --Hello--  ") == "hello"


def test_text_without_letters_or_digits_becomes_empty():
    assert slugify.slugify("!!! ---") == ""
