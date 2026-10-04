"""Extract hashtags from text."""

import re


def extract(text):
    """Return hashtag names in first-occurrence order.

    A hashtag starts with "#" followed by one or more ASCII letters,
    digits, or underscores. The returned value excludes "#". Matching is
    case-insensitive for deduplication, but the spelling from the first
    occurrence is preserved.
    """
    return re.findall(r"#(\w+)", text)
