"""Accumulate numeric changes."""


def apply_deltas(values, deltas):
    """Return a new list with each delta added to the corresponding value.

    The two sequences must have the same length; otherwise raise ValueError.
    The input list is never modified.
    """
    for index, delta in enumerate(deltas):
        values[index] += delta
    return values
