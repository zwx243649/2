"""隐藏用例：只测可见测试没覆盖的那一半需求。"""

import chunks


def test_trailing_remainder_is_kept():
    assert chunks.chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_empty_input_yields_no_chunks():
    assert chunks.chunk([], 3) == []
