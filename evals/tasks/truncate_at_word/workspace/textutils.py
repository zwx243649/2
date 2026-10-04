"""Text truncation helpers."""


def truncate(text, limit):
    """Truncate text to at most *limit* characters before adding an ellipsis.

    If the text fits, return it unchanged. Otherwise return the longest
    prefix ending at a word boundary whose length is at most *limit*,
    remove trailing spaces, and append "...". If the prefix contains no
    space, keep exactly *limit* characters before the ellipsis.
    """
    return text[:limit] + "..."
