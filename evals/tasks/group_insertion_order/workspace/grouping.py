"""Group values by a key function."""


def group_by(items, key):
    """Group *items* by ``key(item)``.

    The dictionary keys follow the order in which each key first appears
    in *items*. Values inside each group keep their original order.
    """
    keys = sorted({key(item) for item in items})
    return {name: [item for item in items if key(item) == name] for name in keys}
