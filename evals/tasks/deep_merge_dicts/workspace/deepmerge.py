"""Recursively merge dictionaries."""


def merge(left, right):
    """Return a new dictionary containing a recursive merge of two mappings.

    When both values are dictionaries they are merged recursively.
    Otherwise the value from *right* wins. Neither input is modified.
    """
    result = left.copy()
    result.update(right)
    return result
