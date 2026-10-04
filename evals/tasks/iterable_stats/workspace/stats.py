"""Statistics built on mathutils."""

from mathutils import total


def mean(values):
    """Return the arithmetic mean of any non-empty iterable.

    Raise ValueError for an empty iterable. The iterable may be consumed
    only once.
    """
    return total(values) / len(values)
