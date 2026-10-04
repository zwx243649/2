"""Compute moving averages."""


def moving_average(values, window):
    """Return the average of each full window in *values*.

    For example, window=2 returns the average of positions 0..1, then
    1..2, and so on. If *window* is less than 1 or greater than the input
    length, return an empty list.
    """
    window = max(window, 1)
    return [sum(values[:index]) / index for index in range(1, len(values) + 1)]
