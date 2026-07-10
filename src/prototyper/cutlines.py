"""Cut-line geometry: registration lines for trimming a packed sheet.

The PRD asks for "thin registration lines ... drawn between/around
components on the sheet to guide scissor/paper-cutter trimming. Not bleed —
content is not extended past the trim line." This module computes those
lines as pure geometry, in the same spirit as :mod:`prototyper.pack`: it
takes the positioned trim boxes of a sheet and returns the line segments to
draw, leaving the actual stroking (width, colour, dash pattern) to the
PDF-assembly stage.

Why full-page grid lines. Because the packing grid is regular, every
component in a column shares the same left/right trim ``x`` and every
component in a row shares the same top/bottom trim ``y``. A straight line
drawn the full length of the page at any trim edge therefore runs only
through gutters and margins — it never crosses a component face — while
still marking exactly where to cut. That suits a scissor/paper-cutter
workflow (one straight cut, edge to edge) and matches the PRD's
"between/around components" phrasing: interior lines fall in the gutters
between components, the outermost lines bound the block.

Lines are derived from the sheet's *actual* placements, not the full grid,
so a partially filled final sheet is marked only around the components it
holds. Placements are treated as their bounding boxes (consistent with
:mod:`prototyper.pack`); hexagonal outlines are not cut-guided in v1 — the
straight-cut model does not apply to them, and a :class:`~prototyper.pack.Placement`
carries no shape to key on.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pack import PackedLayout, Sheet

# Trim edges nearer than this (in inches) are treated as one line, so a
# zero-gutter grid draws a single shared line between abutting components
# rather than two coincident ones. Far below any print precision.
_EPS = 1e-6


@dataclass(frozen=True)
class CutLine:
    """One straight cut guide line, in inches from the page's top-left.

    ``(x1_in, y1_in)`` to ``(x2_in, y2_in)`` are its endpoints. ``orientation``
    is ``"vertical"`` (constant x, ``y1`` < ``y2``) or ``"horizontal"``
    (constant y, ``x1`` < ``x2``); it is redundant with the coordinates but
    saves the renderer from re-deriving it.
    """

    x1_in: float
    y1_in: float
    x2_in: float
    y2_in: float
    orientation: str


def _collapse(values: list[float]) -> list[float]:
    """Return ``values`` sorted with near-duplicates (within ``_EPS``) merged."""
    unique: list[float] = []
    for value in sorted(values):
        if not unique or value - unique[-1] > _EPS:
            unique.append(value)
    return unique


def cut_lines_for_sheet(
    sheet: Sheet,
    *,
    page_width_in: float,
    page_height_in: float,
) -> tuple[CutLine, ...]:
    """Compute the cut lines for one packed :class:`~prototyper.pack.Sheet`.

    Returns a full-page-height vertical line at each distinct component
    left/right trim edge, then a full-page-width horizontal line at each
    distinct top/bottom trim edge — each group ordered left-to-right /
    top-to-bottom. Coincident edges (e.g. abutting components with no gutter)
    collapse to a single line. An empty sheet yields no lines.
    """
    xs: list[float] = []
    ys: list[float] = []
    for placement in sheet.placements:
        xs.append(placement.x_in)
        xs.append(placement.x_in + placement.width_in)
        ys.append(placement.y_in)
        ys.append(placement.y_in + placement.height_in)

    lines: list[CutLine] = []
    for x in _collapse(xs):
        lines.append(CutLine(x, 0.0, x, page_height_in, "vertical"))
    for y in _collapse(ys):
        lines.append(CutLine(0.0, y, page_width_in, y, "horizontal"))
    return tuple(lines)


def cut_lines_for_layout(layout: PackedLayout) -> tuple[tuple[CutLine, ...], ...]:
    """Compute cut lines for every sheet of a :class:`~prototyper.pack.PackedLayout`.

    Convenience over :func:`cut_lines_for_sheet` that reads the page size
    from the layout itself; returns one tuple of :class:`CutLine`\\ s per
    sheet, in sheet order.
    """
    return tuple(
        cut_lines_for_sheet(
            sheet,
            page_width_in=layout.page_width_in,
            page_height_in=layout.page_height_in,
        )
        for sheet in layout.sheets
    )
