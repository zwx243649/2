"""Tests for countertool.py."""

import countertool


def test_counts_events_by_name():
    counter = countertool.Counter()
    counter.add("read")
    counter.add("read")
    counter.add("write")
    assert counter.snapshot() == {"read": 2, "write": 1}


def test_snapshot_does_not_alias_internal_state():
    counter = countertool.Counter()
    counter.add("read", 2)
    snap = counter.snapshot()
    snap["read"] = 99
    assert counter.snapshot() == {"read": 2}
