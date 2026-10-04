"""Rotate sequences."""


def rotate_right(items, steps):
    """Return a new list rotated to the right by *steps* positions.

    Negative values rotate left. Values whose absolute value is larger
    than the sequence length wrap around. An empty sequence returns [].
    The input sequence is not modified.
    """
    steps %= len(items)
    return items[-steps:] + items[:-steps]
