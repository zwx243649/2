"""Tests for templating.py."""

import templating


def test_single_placeholder():
    assert templating.render("Hello {name}", {"name": "Ada"}) == "Hello Ada"


def test_missing_placeholder_is_unchanged():
    assert templating.render("Hello {name}", {}) == "Hello {name}"
