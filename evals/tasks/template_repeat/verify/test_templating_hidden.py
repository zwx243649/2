"""Hidden tests for templating.py."""

import templating


def test_every_occurrence_is_replaced():
    assert templating.render("{x}+{x}", {"x": "2"}) == "2+2"


def test_missing_and_known_placeholders_can_mix():
    assert templating.render("{a}/{b}", {"a": "1"}) == "1/{b}"


def test_replacement_text_is_literal():
    assert templating.render("{x}", {"x": "{y}"}) == "{y}"
