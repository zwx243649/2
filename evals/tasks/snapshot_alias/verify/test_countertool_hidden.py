"""Hidden tests for countertool.py."""

import countertool


def test_new_events_do_not_change_an_older_snapshot():
    counter = countertool.Counter()
    counter.add("a")
    before = counter.snapshot()
    counter.add("a")
    assert before == {"a": 1}
    assert counter.snapshot() == {"a": 2}


def test_add_returns_the_new_count():
    counter = countertool.Counter()
    assert counter.add("x", 3) == 3
    assert counter.add("x", 2) == 5
