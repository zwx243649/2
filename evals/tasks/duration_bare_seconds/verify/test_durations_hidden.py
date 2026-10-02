"""隐藏用例：只测可见测试没覆盖的那一半需求。"""

import durations


def test_bare_number_is_seconds():
    assert durations.parse_duration("45") == 45


def test_mixed_with_trailing_bare_number():
    assert durations.parse_duration("1h30") == 3630
