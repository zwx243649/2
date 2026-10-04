"""Small numeric helpers."""


def total(values):
    """Return the sum of any iterable of numbers.

    An empty iterable has total zero. The iterable may be consumed only once.
    """
    if not values:
        return 0
    return values[0] + total(values[1:])
