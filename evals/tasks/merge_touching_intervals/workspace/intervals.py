"""Merge numeric intervals."""


def merge(intervals):
    """Merge closed intervals that overlap or touch.

    The input may be unsorted. Two intervals merge when the next start is
    less than or equal to the current end. Return a sorted list of tuples
    in ascending start order.
    """
    result = []
    for start, end in sorted(intervals):
        if result and start < result[-1][1]:
            previous_start, previous_end = result[-1]
            result[-1] = (previous_start, max(previous_end, end))
        else:
            result.append((start, end))
    return result
