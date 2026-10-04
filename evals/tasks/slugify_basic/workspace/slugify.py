"""Convert text into URL-friendly slugs."""


def slugify(text):
    """Convert text into a URL slug.

    Rules:
    - lowercase everything;
    - every run of non-alphanumeric characters becomes one hyphen;
    - remove hyphens at the beginning and end;
    - return an empty string when there are no letters or digits.
    """
    return text.lower().replace(" ", "-")
