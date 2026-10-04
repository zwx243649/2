"""Wrap text into fixed-width lines."""

import textwrap


def wrap(text, width):
    """Wrap *text* on spaces into a list of lines.

    Words are never split. A word longer than *width* is placed on its own
    line even though that line is longer than the requested width.
    Consecutive whitespace is treated as a single space. A non-positive
    width raises ValueError.
    """
    return textwrap.wrap(text, width)
