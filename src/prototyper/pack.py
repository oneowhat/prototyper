"""Auto-grid page packing: fit components onto 8.5x11 sheets.

The PRD's page-layout model is an auto-packed grid — "the tool computes how
many components fit per 8.5x11 sheet given component size and fills sheets in
data order". This module is that computation, and nothing more: it is pure
geometry. Given how many components there are (a *count*, not the data or the
rendered HTML), a :class:`~prototyper.sizing.ResolvedSize`, and the layout
hints (margin, gutter), it returns a :class:`PackedLayout` — a list of
:class:`Sheet`\\ s, each holding the :class:`Placement`\\ s (positioned trim
boxes) of the components that land on that page, in data order.

Downstream stages consume this: cut-line rendering draws around each
placement's rectangle, and PDF assembly positions each rendered component at
its placement. Keeping packing decoupled from rendering means it can be
tested with plain numbers and reasoned about independently.

Design choices, consistent with the rest of the pipeline:

- **Inches throughout.** Sizes already arrive in inches from
  :mod:`prototyper.sizing`; the page is 8.5x11in, so inches are the native
  unit. Margin and gutter are taken as inches too (the caller resolves the
  config's length strings via :func:`prototyper.sizing.parse_length`).
- **Top-left anchored at the margin.** The grid starts exactly at the
  designer's margin rather than being centred in the usable area, so the
  margin they set is the margin they get; leftover space collects at the
  right/bottom. This also keeps cut-line coordinates predictable.
- **Bounding-box packing.** A component occupies its ``width x height``
  rectangle regardless of ``shape``; a hex token packs by its bounding box.
  The ``shape`` only matters later, to cut-line rendering.
- **Fail loud** (the stance the sizing task deferred here): a component that
  cannot fit even once on a page — too wide, too tall, or squeezed out by an
  oversized margin — raises :class:`PackError` rather than silently producing
  empty sheets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .sizing import ResolvedSize

# US Letter, the tool's fixed output page (PRD: "8.5x11 output page").
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0

# Tolerance for grid-count arithmetic so a component that fits *exactly* (an
# integer number of columns/rows filling the usable area to the millimetre)
# isn't dropped by floating-point drift. 1e-6in is far below print precision.
_EPS = 1e-6


class PackError(Exception):
    """Raised when components can't be packed onto the page as configured."""


@dataclass(frozen=True)
class Placement:
    """One component positioned on a sheet.

    ``index`` is the component's position in the input data (0-based, data
    order). ``x_in``/``y_in`` are the trim box's top-left corner, measured in
    inches from the top-left of the page. ``width_in``/``height_in`` repeat
    the component's size so a placement is a self-contained "draw this
    rectangle here" instruction for the cut-line and PDF stages.
    """

    index: int
    x_in: float
    y_in: float
    width_in: float
    height_in: float


@dataclass(frozen=True)
class Sheet:
    """One 8.5x11 page's worth of placed components, in data order."""

    placements: tuple[Placement, ...]


@dataclass(frozen=True)
class PackedLayout:
    """The full packing result: sheets plus the grid geometry that produced them."""

    sheets: tuple[Sheet, ...]
    columns: int
    rows: int
    page_width_in: float
    page_height_in: float


def _grid_count(usable_in: float, size_in: float, gutter_in: float) -> int:
    """How many ``size_in`` cells (separated by ``gutter_in``) fit in ``usable_in``.

    ``n`` cells occupy ``n*size + (n-1)*gutter`` inches, so
    ``n = floor((usable + gutter) / (size + gutter))``. Returns 0 if not even
    one fits.
    """
    pitch = size_in + gutter_in
    return int((usable_in + gutter_in + _EPS) / pitch)


def pack_components(
    count: int,
    size: ResolvedSize,
    *,
    margin_in: float = 0.5,
    gutter_in: float = 0.1,
    page_breaks: Iterable[int] = (),
    page_width_in: float = PAGE_WIDTH_IN,
    page_height_in: float = PAGE_HEIGHT_IN,
) -> PackedLayout:
    """Pack ``count`` components of ``size`` onto as many sheets as needed.

    Components fill each sheet's grid left-to-right, top-to-bottom, in data
    order, spilling onto a new sheet when the current one is full. ``margin_in``
    is the clear border on all four sides; ``gutter_in`` is the space between
    adjacent components. ``page_breaks`` is an optional iterable of data
    indices that must each begin a fresh sheet (the PRD's forced page breaks);
    a break at index 0 or a full-page boundary is a harmless no-op.

    Returns a :class:`PackedLayout`. Raises :class:`PackError` if ``count`` is
    negative, if the margin/gutter are negative, or if the component cannot fit
    on the page even once (too wide, too tall, or crowded out by the margin).
    """
    if count < 0:
        raise PackError(f"component count must be non-negative, got {count}")
    if margin_in < 0:
        raise PackError(f"margin must be non-negative, got {margin_in}in")
    if gutter_in < 0:
        raise PackError(f"gutter must be non-negative, got {gutter_in}in")

    usable_width = page_width_in - 2 * margin_in
    usable_height = page_height_in - 2 * margin_in

    columns = _grid_count(usable_width, size.width_in, gutter_in)
    rows = _grid_count(usable_height, size.height_in, gutter_in)

    if columns < 1:
        raise PackError(
            f"component is too wide to fit: {size.width_in}in wide needs to fit "
            f"in {usable_width:.3g}in of usable width "
            f"({page_width_in}in page minus 2x{margin_in}in margin)"
        )
    if rows < 1:
        raise PackError(
            f"component is too tall to fit: {size.height_in}in tall needs to fit "
            f"in {usable_height:.3g}in of usable height "
            f"({page_height_in}in page minus 2x{margin_in}in margin)"
        )

    per_page = columns * rows
    pitch_w = size.width_in + gutter_in
    pitch_h = size.height_in + gutter_in
    breaks = set(page_breaks)

    sheets: list[Sheet] = []
    current: list[Placement] = []
    for i in range(count):
        if current and (len(current) == per_page or i in breaks):
            sheets.append(Sheet(tuple(current)))
            current = []
        pos = len(current)
        col = pos % columns
        row = pos // columns
        current.append(
            Placement(
                index=i,
                x_in=margin_in + col * pitch_w,
                y_in=margin_in + row * pitch_h,
                width_in=size.width_in,
                height_in=size.height_in,
            )
        )
    if current:
        sheets.append(Sheet(tuple(current)))

    return PackedLayout(
        sheets=tuple(sheets),
        columns=columns,
        rows=rows,
        page_width_in=page_width_in,
        page_height_in=page_height_in,
    )
