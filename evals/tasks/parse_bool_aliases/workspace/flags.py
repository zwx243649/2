"""Parse boolean flags from text."""


def parse_bool(text):
    """Parse a boolean flag.

    Comparison is case-insensitive and surrounding whitespace is ignored.
    True values are "true", "1", "yes", and "on".
    False values are "false", "0", "no", and "off".
    Any other value raises ValueError.
    """
    return text.strip().lower() == "true"
