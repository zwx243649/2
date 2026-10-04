"""Hidden tests for hashtags.py."""

import hashtags


def test_order_and_mixed_categories():
    assert hashtags.extract("#first #Second #third") == ["first", "Second", "third"]


def test_underscores_and_digits_are_part_of_the_tag():
    assert hashtags.extract("#v2_beta") == ["v2_beta"]


def test_hash_without_a_tag_is_ignored():
    assert hashtags.extract("# #word") == ["word"]
