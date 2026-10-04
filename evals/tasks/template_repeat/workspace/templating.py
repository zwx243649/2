"""Render simple {name} placeholders."""


def render(template, values):
    """Replace placeholders in *template* using the *values* mapping.

    Every occurrence of ``{name}`` is replaced by ``values["name"]``.
    Placeholders whose name is missing from the mapping are left unchanged.
    Extra mapping entries that do not appear in the template are ignored.
    Replacement values are inserted literally.
    """
    return template.format(**values)
