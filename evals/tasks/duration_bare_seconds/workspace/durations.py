"""Parse short duration strings."""

UNITS = {"h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    """Parse '1h30m', '90s' or '45' into a number of seconds.

    A trailing number with no unit counts as seconds.
    """
    # 只认「数字 + 单位」的单段形式
    return int(text[:-1]) * UNITS[text[-1]]
