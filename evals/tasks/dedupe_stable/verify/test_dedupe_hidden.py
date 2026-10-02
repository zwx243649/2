"""隐藏用例：只测可见测试没覆盖的那一半需求。"""

import dedupe


def test_order_of_first_occurrence_is_preserved():
    assert dedupe.dedupe([3, 1, 3, 2, 1]) == [3, 1, 2]
