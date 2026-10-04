"""Binary search helpers."""

import bisect


def find_last(values, target):
    """Find the index of the last occurrence of *target*.

    *values* is sorted in ascending order. Return -1 when the target is
    not present. Duplicate values are allowed.
    """
    return bisect.bisect_left(values, target)
