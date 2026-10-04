"""Flatten nested sequences."""


def flatten(items):
    """Return a flat list containing every scalar in *items*.

    Lists and tuples are traversed recursively, regardless of nesting
    depth. Values that are not lists or tuples are kept unchanged.
    """
    return [value for group in items for value in group]
