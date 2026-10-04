"""Tests for slugify.py."""

import slugify


def test_spaces_become_hyphens():
    assert slugify.slugify("Hello World") == "hello-world"


def test_punctuation_is_removed():
    assert slugify.slugify("Hello, World!") == "hello-world"
