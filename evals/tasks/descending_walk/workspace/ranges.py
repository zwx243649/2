"""Helpers for walking numeric ranges."""


def walk(start, end):
    """Return every integer between *start* and *end*, inclusive.

    The sequence descends when *start* is greater than *end*.
    """
    return list(range(start, end))
