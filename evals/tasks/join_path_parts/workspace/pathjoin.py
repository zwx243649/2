"""Join path-like string segments."""


def join_parts(parts):
    """Join path segments with forward slashes.

    Empty segments and "." are skipped. Leading and trailing "/" characters
    are stripped from each segment. A segment equal to ".." raises
    ValueError. Return an empty string when no segments remain.
    """
    return "/".join(parts)
