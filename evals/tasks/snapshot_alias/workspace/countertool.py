"""A small counter with snapshots."""


class Counter:
    """Count events by name."""

    def __init__(self):
        self.counts = {}

    def add(self, name, amount=1):
        """Add *amount* to the count for *name* and return the new count."""
        self.counts[name] = self.counts.get(name, 0) + amount
        return self.counts[name]

    def snapshot(self):
        """Return an independent copy of the current counts."""
        return self.counts
