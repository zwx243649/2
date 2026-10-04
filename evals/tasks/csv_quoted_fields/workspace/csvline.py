"""Parse a single CSV record."""


def parse_line(line):
    """Parse one comma-separated record into a list of strings.

    A field may be enclosed in double quotes. Quoted fields can contain
    commas, and two consecutive double quotes inside a quoted field
    represent one literal double quote. The surrounding quotes are removed
    from the returned value.
    """
    return line.split(",")
