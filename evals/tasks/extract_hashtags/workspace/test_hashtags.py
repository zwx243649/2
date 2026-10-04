"""Tests for hashtags.py."""

import hashtags


def test_extracts_plain_hashtag():
    assert hashtags.extract("hello #python") == ["python"]


def test_duplicate_hashtags_are_removed():
    assert hashtags.extract("#Tag and #tag") == ["Tag"]
