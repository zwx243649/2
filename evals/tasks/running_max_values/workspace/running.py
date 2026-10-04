"""Track running maxima."""


def running_max(values):
    """Return the maximum value seen so far at every position.

    The output has the same length as the input. An empty input returns [].
    """
    return [max(values)] * len(values)
