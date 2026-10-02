"""Tests for durations.py."""

import durations


def test_hours_and_minutes():
    assert durations.parse_duration("1h30m") == 5400


def test_seconds_suffix():
    assert durations.parse_duration("90s") == 90
