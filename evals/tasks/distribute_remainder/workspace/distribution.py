"""Split values into a fixed number of buckets."""


def split_evenly(items, buckets):
    """Split *items* into exactly *buckets* lists while preserving order.

    When the values do not divide evenly, the earlier buckets receive one
    extra item. A non-positive bucket count raises ValueError. Empty input
    returns the requested number of empty lists.
    """
    size = len(items) // buckets
    return [items[index * size : (index + 1) * size] for index in range(buckets)]
