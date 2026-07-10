"""Single-component rendering: one HTML/CSS template + one data row -> HTML.

The PRD's design model is "one card/board/token defined once as an HTML/CSS
template and instantiated once per row of input data", with data fields
injected via Jinja2 -- no custom scripting language. This module renders a
*single* component: given the project's template file and one row from the CSV
(a ``{header: value}`` mapping, as produced by the data loader) it returns the
substituted HTML string for that one component. Packing many components onto an
8.5x11 sheet and assembling the PDF are separate downstream stages; this stage
produces the HTML for exactly one component.

Design choices, consistent with the config and data loaders being strict about
things that silently ruin a print run:

- **StrictUndefined**: a placeholder naming a column the data does not have (a
  typo like ``{{ nmae }}``) raises :class:`RenderError` instead of rendering a
  blank -- the designer finds out before printing a whole deck. Optional fields
  are still expressible with the standard ``{{ field | default('') }}`` filter,
  which keeps working under StrictUndefined.
- **Autoescaping on**: a data value containing ``<``, ``&`` or ``"`` is escaped
  so it cannot produce broken HTML. Designers write markup in the template; data
  supplies text.
- **FileSystemLoader rooted at the template's directory** so ``{% include %}``
  and ``{% extends %}`` resolve relative to the template file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import jinja2


class RenderError(Exception):
    """Raised when a template is missing, malformed, or references unknown data."""


def render_component(template_path: str | Path, row: Mapping[str, str]) -> str:
    """Render a single component's HTML from a template and one data row.

    ``template_path`` is the HTML/CSS Jinja2 template; ``row`` is a mapping of
    column header to (string) value, whose keys become top-level template
    variables (``{{ name }}``). Returns the rendered HTML string.

    Raises :class:`RenderError` for a missing template file, a template syntax
    error, or a placeholder that references a field absent from ``row``.
    """
    template_path = Path(template_path)
    if not template_path.is_file():
        raise RenderError(f"No template file found at {template_path}")

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_path.parent)),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
    )

    try:
        template = env.get_template(template_path.name)
    except jinja2.TemplateSyntaxError as exc:
        raise RenderError(
            f"{template_path}: template syntax error on line {exc.lineno}: {exc.message}"
        ) from exc

    try:
        return template.render(dict(row))
    except jinja2.UndefinedError as exc:
        raise RenderError(
            f"{template_path}: template uses a field not present in the data row: {exc.message}"
        ) from exc
