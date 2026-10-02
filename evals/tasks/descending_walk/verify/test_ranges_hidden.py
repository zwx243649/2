"""隐藏用例：只测可见测试没覆盖的那一半需求。"""

import ranges


def test_descending_range():
    assert ranges.walk(4, 1) == [4, 3, 2, 1]


def test_descending_by_two():
    assert ranges.walk(3, -1) == [3, 2, 1, 0, -1]
