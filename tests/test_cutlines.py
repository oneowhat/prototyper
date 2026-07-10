"""Tests for cut-line rendering (task: Add cut line rendering).

Cut lines are pure geometry, in the same spirit as the packing engine: given
a packed sheet's positioned trim boxes, compute the straight registration
lines a designer follows to trim the components apart. Because the grid is
regular, a full-page line drawn at any trim edge runs only through gutters
and margins (never across a component face), which is exactly what a
scissor/paper-cutter workflow wants. These tests work from plain
placements/counts and assert coordinates, not rendered output.
"""

import pytest

from prototyper.cutlines import (
    CutLine,
    cut_lines_for_layout,
    cut_lines_for_sheet,
)
from prototyper.pack import Placement, Sheet, pack_components
from prototyper.sizing import ResolvedSize


POKER = ResolvedSize(2.5, 3.5, "rect")


def _sheet(*boxes):
    """Build a Sheet from ``(x, y, w, h)`` tuples, indexed in order."""
    return Sheet(
        tuple(
            Placement(index=i, x_in=x, y_in=y, width_in=w, height_in=h)
            for i, (x, y, w, h) in enumerate(boxes)
        )
    )


# --- a single component ----------------------------------------------------


def test_single_card_has_a_line_at_each_of_its_four_edges():
    sheet = _sheet((0.5, 0.5, 2.5, 3.5))
    lines = cut_lines_for_sheet(sheet, page_width_in=8.5, page_height_in=11.0)

    verticals = [l for l in lines if l.orientation == "vertical"]
    horizontals = [l for l in lines if l.orientation == "horizontal"]
    assert [l.x1_in for l in verticals] == pytest.approx([0.5, 3.0])
    assert [l.y1_in for l in horizontals] == pytest.approx([0.5, 4.0])


def test_lines_span_the_full_page():
    sheet = _sheet((0.5, 0.5, 2.5, 3.5))
    lines = cut_lines_for_sheet(sheet, page_width_in=8.5, page_height_in=11.0)

    for l in lines:
        if l.orientation == "vertical":
            assert l.x1_in == pytest.approx(l.x2_in)
            assert (l.y1_in, l.y2_in) == pytest.approx((0.0, 11.0))
        else:
            assert l.y1_in == pytest.approx(l.y2_in)
            assert (l.x1_in, l.x2_in) == pytest.approx((0.0, 8.5))


def test_returns_cutline_instances():
    lines = cut_lines_for_sheet(
        _sheet((0.5, 0.5, 2.5, 3.5)), page_width_in=8.5, page_height_in=11.0
    )
    assert lines and all(isinstance(l, CutLine) for l in lines)


# --- gutters and shared edges ----------------------------------------------


def test_gutter_grid_draws_a_line_at_every_trim_edge():
    # Two columns separated by a 0.1in gutter: distinct edges at each border.
    sheet = _sheet((0.5, 0.5, 2.5, 3.5), (3.1, 0.5, 2.5, 3.5))
    lines = cut_lines_for_sheet(sheet, page_width_in=8.5, page_height_in=11.0)

    xs = [l.x1_in for l in lines if l.orientation == "vertical"]
    assert xs == pytest.approx([0.5, 3.0, 3.1, 5.6])


def test_touching_components_share_one_cut_line():
    # Abutting columns (zero gutter): the shared edge yields ONE line, not two.
    sheet = _sheet((0.5, 0.5, 2.5, 3.5), (3.0, 0.5, 2.5, 3.5))
    lines = cut_lines_for_sheet(sheet, page_width_in=8.5, page_height_in=11.0)

    xs = [l.x1_in for l in lines if l.orientation == "vertical"]
    assert xs == pytest.approx([0.5, 3.0, 5.5])


# --- ordering and empties --------------------------------------------------


def test_lines_are_ordered_vertical_then_horizontal():
    layout = pack_components(4, POKER)
    lines = cut_lines_for_sheet(
        layout.sheets[0],
        page_width_in=layout.page_width_in,
        page_height_in=layout.page_height_in,
    )
    first_h = next(i for i, l in enumerate(lines) if l.orientation == "horizontal")
    assert all(l.orientation == "vertical" for l in lines[:first_h])
    assert all(l.orientation == "horizontal" for l in lines[first_h:])


def test_empty_sheet_has_no_cut_lines():
    assert cut_lines_for_sheet(Sheet(()), page_width_in=8.5, page_height_in=11.0) == ()


# --- integration with the packing engine -----------------------------------


def test_full_grid_sheet_has_a_line_at_every_edge():
    # 2x2 grid -> 4 distinct vertical edges and 4 distinct horizontal edges.
    layout = pack_components(4, POKER, margin_in=0.5, gutter_in=0.1)
    lines = cut_lines_for_sheet(
        layout.sheets[0],
        page_width_in=layout.page_width_in,
        page_height_in=layout.page_height_in,
    )
    assert sum(1 for l in lines if l.orientation == "vertical") == 4
    assert sum(1 for l in lines if l.orientation == "horizontal") == 4


def test_layout_helper_marks_each_sheet_from_its_own_placements():
    # 2x2 = 4 per page; 5 cards -> last sheet holds a single card.
    layout = pack_components(5, POKER, margin_in=0.5, gutter_in=0.1)
    per_sheet = cut_lines_for_layout(layout)

    assert len(per_sheet) == len(layout.sheets)
    last = per_sheet[-1]
    assert sum(1 for l in last if l.orientation == "vertical") == 2
    assert sum(1 for l in last if l.orientation == "horizontal") == 2
