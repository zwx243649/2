"""Split sequences into fixed-size chunks."""


def chunk(items, size):
    """Split *items* into consecutive chunks of at most *size*.

    The final chunk holds the remainder, so it may be shorter.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i : i + size] for i in range(0, len(items) - size + 1, size)]
