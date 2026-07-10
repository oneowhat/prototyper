"""PDF assembly: paint packed sheets into a print-ready multi-page PDF.

This is where the pipeline's pure-geometry results become an actual
document. It consumes three things the earlier stages produced:

- a :class:`~prototyper.pack.PackedLayout` — which component lands on which
  8.5x11 sheet, and at what trim-box coordinates;
- the already-rendered HTML for each component, one string per data row (as
  produced by :func:`prototyper.render.render_component`), indexed by the
  component's data index; and
- optionally, the cut lines for each sheet (from
  :mod:`prototyper.cutlines`) — passed in precomputed so this module stays
  decoupled from cut-line geometry, exactly as packing and cut-line
  computation are decoupled from each other.

The work splits in two so the bulk of it is testable without a working
WeasyPrint install (which needs native Pango/Cairo/GObject libraries):

- :func:`build_document_html` is **pure**. It assembles a single HTML/CSS
  document whose ``@page`` matches the output page and in which every sheet
  is one printed page, every component is absolutely positioned at its trim
  box, and every cut line is a thin bordered div. All input validation
  happens here.
- :func:`assemble_pdf` is the thin wrapper that hands that document to
  WeasyPrint (imported lazily) and writes the PDF bytes.

Layout model. Each sheet is a ``position: relative`` block exactly the page
size, and page breaks are forced with ``.sheet + .sheet { break-before:
page }`` — a break *before* every sheet after the first, rather than *after*
each sheet, so the final page doesn't spill into a trailing blank one.
Components are ``position: absolute`` divs offset from the sheet's top-left
by their placement, carrying their own trim width/height; the rendered
component HTML is embedded verbatim inside. Cut lines are drawn first (so a
component face always sits on top of any coincident edge) as zero-content
divs whose single ``border-left``/``border-top`` is the stroke, centred on
the trim edge via a negative margin.

Cut-line styling (weight, colour, dash) is a PRD open question; this module
picks conservative defaults — a thin solid black line — and exposes them via
:class:`CutLineStyle` so the build command can override them later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .cutlines import CutLine
from .pack import PackedLayout, Placement


class PdfError(Exception):
    """Raised when a PDF can't be assembled from the given inputs."""


@dataclass(frozen=True)
class CutLineStyle:
    """How cut lines are stroked.

    ``width_pt`` is the line weight in points, ``color`` any CSS colour, and
    ``css_style`` the CSS border-style keyword (``"solid"``, ``"dashed"``,
    ``"dotted"``). These map directly onto the ``border-left``/``border-top``
    shorthand used to draw each line.
    """

    width_pt: float = 0.25
    color: str = "#000000"
    css_style: str = "solid"


# Thin solid black cut guides by default (PRD leaves exact styling open).
DEFAULT_CUT_LINE_STYLE = CutLineStyle()


def _fmt_in(value: float) -> str:
    """Format an inch measurement compactly (trimming float noise)."""
    return f"{value:g}in"


def _stylesheet(page_width_in: float, page_height_in: float) -> str:
    """The document's CSS: page size, sheet pages, component/cut-line boxes."""
    return (
        f"@page {{ size: {page_width_in:g}in {page_height_in:g}in; margin: 0; }}\n"
        "html, body { margin: 0; padding: 0; }\n"
        f".sheet {{ position: relative; width: {page_width_in:g}in; "
        f"height: {page_height_in:g}in; overflow: hidden; }}\n"
        # Break *before* every sheet after the first, so no trailing blank page.
        ".sheet + .sheet { break-before: page; }\n"
        ".component { position: absolute; overflow: hidden; box-sizing: border-box; }\n"
        ".cut-line { position: absolute; }\n"
    )


def _component_div(placement: Placement, inner_html: str) -> str:
    style = (
        f"left: {_fmt_in(placement.x_in)}; "
        f"top: {_fmt_in(placement.y_in)}; "
        f"width: {_fmt_in(placement.width_in)}; "
        f"height: {_fmt_in(placement.height_in)};"
    )
    return f'<div class="component" style="{style}">{inner_html}</div>'


def _cut_line_div(line: CutLine, style: CutLineStyle) -> str:
    border = f"{style.width_pt:g}pt {style.css_style} {style.color}"
    half = style.width_pt / 2.0
    if line.orientation == "vertical":
        css = (
            f"left: {_fmt_in(line.x1_in)}; top: 0; height: 100%; "
            f"border-left: {border}; margin-left: -{half:g}pt;"
        )
    else:
        css = (
            f"top: {_fmt_in(line.y1_in)}; left: 0; width: 100%; "
            f"border-top: {border}; margin-top: -{half:g}pt;"
        )
    return f'<div class="cut-line" style="{css}"></div>'


def build_document_html(
    layout: PackedLayout,
    components: Sequence[str],
    *,
    cut_lines: Sequence[Sequence[CutLine]] | None = None,
    cut_line_style: CutLineStyle = DEFAULT_CUT_LINE_STYLE,
) -> str:
    """Assemble the single HTML/CSS document WeasyPrint paints into a PDF.

    ``components`` is the rendered HTML for each component, indexed by data
    index (as carried on each :class:`~prototyper.pack.Placement`).
    ``cut_lines``, if given, is one sequence of :class:`~prototyper.cutlines.CutLine`
    per sheet, in sheet order (typically :func:`prototyper.cutlines.cut_lines_for_layout`);
    omit it to draw no cut lines. ``cut_line_style`` controls their stroke.

    Returns the document as a string. Raises :class:`PdfError` if a placement
    references a component index with no rendered HTML, or if ``cut_lines`` is
    provided but its length doesn't match the number of sheets.
    """
    if cut_lines is not None and len(cut_lines) != len(layout.sheets):
        raise PdfError(
            f"cut line groups ({len(cut_lines)}) must match the number of "
            f"sheets ({len(layout.sheets)})"
        )

    body_parts: list[str] = []
    for sheet_i, sheet in enumerate(layout.sheets):
        pieces: list[str] = []
        # Cut lines first, so component faces paint over any coincident edge.
        if cut_lines is not None:
            for line in cut_lines[sheet_i]:
                pieces.append(_cut_line_div(line, cut_line_style))
        for placement in sheet.placements:
            if not 0 <= placement.index < len(components):
                raise PdfError(
                    f"no rendered component for data index {placement.index} "
                    f"(have {len(components)} component(s))"
                )
            pieces.append(_component_div(placement, components[placement.index]))
        body_parts.append('<div class="sheet">' + "".join(pieces) + "</div>")

    stylesheet = _stylesheet(layout.page_width_in, layout.page_height_in)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<style>\n{stylesheet}</style>\n"
        "</head>\n"
        "<body>\n"
        + "\n".join(body_parts)
        + "\n</body>\n</html>\n"
    )


def assemble_pdf(
    layout: PackedLayout,
    components: Sequence[str],
    output_path: str | Path,
    *,
    cut_lines: Sequence[Sequence[CutLine]] | None = None,
    cut_line_style: CutLineStyle = DEFAULT_CUT_LINE_STYLE,
    base_url: str | Path | None = None,
) -> Path:
    """Render the packed layout to a multi-page PDF at ``output_path``.

    Builds the document with :func:`build_document_html` (which performs all
    input validation, before WeasyPrint is imported) and writes the PDF via
    WeasyPrint. ``base_url`` is the directory relative-path assets (images,
    fonts) in the templates resolve against — pass the project directory; it
    defaults to ``output_path``'s parent.

    Returns the output path as a :class:`~pathlib.Path`. Raises
    :class:`PdfError` for invalid inputs (see :func:`build_document_html`) or
    if WeasyPrint is unavailable.
    """
    output_path = Path(output_path)
    document = build_document_html(
        layout,
        components,
        cut_lines=cut_lines,
        cut_line_style=cut_line_style,
    )

    try:
        from weasyprint import HTML
    except Exception as exc:  # ImportError, or OSError from missing native libs
        raise PdfError(
            "WeasyPrint is required to write PDFs but could not be loaded "
            f"({exc}). See https://doc.courtbouillon.org/weasyprint/stable/"
            "first_steps.html#installation"
        ) from exc

    resolved_base = str(base_url) if base_url is not None else str(output_path.parent)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=document, base_url=resolved_base).write_pdf(str(output_path))
    return output_path
