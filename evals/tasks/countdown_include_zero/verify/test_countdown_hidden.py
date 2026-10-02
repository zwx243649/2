"""隐藏用例：只测可见测试没覆盖的那一半需求。"""

import countdown


def test_zero_is_included():
    assert countdown.countdown(3) == [3, 2, 1, 0]


def test_start_at_zero():
    assert countdown.countdown(0) == [0]
