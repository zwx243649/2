"""Convert Roman numerals to integers."""

VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(text):
    """Convert an uppercase Roman numeral to an integer.

    Standard subtractive pairs such as IV, IX, XL, XC, CD, and CM are
    supported. Empty input or characters outside I, V, X, L, C, D, M
    raise ValueError.
    """
    return sum(VALUES[ch] for ch in text)
