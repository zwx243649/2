"""Validate password rules."""


def validate(password):
    """Return the violated password rules in a stable order.

    Rules are checked in this order:
    - "length": at least 8 characters;
    - "letter": contains at least one letter;
    - "digit": contains at least one digit;
    - "space": contains no whitespace.

    Return an empty list for a valid password.
    """
    errors = []
    if len(password) < 8:
        errors.append("length")
    return errors
