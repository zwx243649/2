from __future__ import annotations

from harness.tools import ToolResultCache


def test_long_identical_results_are_deduplicated():
    cache = ToolResultCache()
    value = "x" * 200

    assert cache.remember("文件内容", "a.py", value) == value
    assert "重复内容已省略" in cache.remember("文件内容", "a.py", value)


def test_changed_result_is_returned_in_full():
    cache = ToolResultCache()

    cache.remember("文件内容", "a.py", "x" * 200)
    changed = "y" * 200

    assert cache.remember("文件内容", "a.py", changed) == changed


def test_short_results_are_not_deduplicated():
    cache = ToolResultCache()

    assert cache.remember("文件内容", "a.py", "short") == "short"
    assert cache.remember("文件内容", "a.py", "short") == "short"


def test_dedupe_can_be_disabled():
    cache = ToolResultCache(enabled=False)
    value = "x" * 200

    assert cache.remember("文件内容", "a.py", value) == value
    assert cache.remember("文件内容", "a.py", value) == value
