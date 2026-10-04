"""Parse semantic version strings."""

import re

PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse(text):
    """Parse exactly MAJOR.MINOR.PATCH into a tuple of integers.

    Each component is a non-negative integer. Leading zeroes are allowed
    only for the value zero itself. The whole string must match: whitespace,
    a leading "v", or a suffix such as "-beta" makes the input invalid.
    Invalid input raises ValueError.
    """
    match = PATTERN.search(text)
    if match is None:
        raise ValueError("invalid version")
    return tuple(int(part) for part in match.groups())
