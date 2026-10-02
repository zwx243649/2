"""隐藏用例：只测可见测试没覆盖的那一半需求。"""

import clamping


def test_reversed_bounds_are_swapped():
    assert clamping.clamp(5, 10, 0) == 5
