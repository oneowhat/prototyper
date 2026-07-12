"""Tests for the auto-grid page packing engine (task: Build auto-grid page
packing engine).

Packing is pure geometry: given a resolved component size, the 8.5x11 page,
and the layout hints (margin, gutter), compute how many components fit per
sheet and place them in data order across as many sheets as needed. The
result is a set of positioned rectangles the cut-line and PDF-assembly
stages draw from; this module renders no HTML and reads no data — it works
from a component *count* and refers back to each item by its data index.
"""

import pytest

from prototyper.pack import (
    PAGE_HEIGHT_IN,
    PAGE_WIDTH_IN,
    PackedLayout,
    PackError,
    Placement,
    Sheet,
    pack_components,
)
from prototyper.sizing import ResolvedSize


POKER = ResolvedSize(2.5, 3.5, "rect")


# --- grid computation ------------------------------------------------------


def test_letter_page_dimensions():
    assert (PAGE_WIDTH_IN, PAGE_HEIGHT_IN) == (8.5, 11.0)


def test_poker_grid_on_letter_with_defaults():
    # usable width  = 8.5 - 2*0.5 = 7.5; (7.5+0.1)/(2.5+0.1) = 2.92 -> 2 cols
    # usable height = 11  - 2*0.5 = 10 ; (10 +0.1)/(3.5+0.1) = 2.80 -> 2 rows
    layout = pack_components(4, POKER, margin_in=0.5, gutter_in=0.1)
    assert (layout.columns, layout.rows) == (2, 2)
    assert len(layout.sheets) == 1
    assert len(layout.sheets[0].placements) == 4


def test_exact_fit_is_not_lost_to_floating_point():
    # Choose a margin so three 2.5in columns + two 0.1in gutters fill the
    # usable width *exactly* (7.7in). The boundary must round to 3, not 2.
    layout = pack_components(3, POKER, margin_in=0.4, gutter_in=0.1)
    assert layout.columns == 3


def test_zero_gutter_packs_tighter():
    tight = pack_components(1, POKER, margin_in=0.5, gutter_in=0.0)
    loose = pack_components(1, POKER, margin_in=0.5, gutter_in=0.1)
    assert tight.columns >= loose.columns
    assert tight.rows >= loose.rows


def test_returns_packed_layout_type():
    layout = pack_components(1, POKER)
    assert isinstance(layout, PackedLayout)
    assert isinstance(layout.sheets[0], Sheet)
    assert isinstance(layout.sheets[0].placements[0], Placement)


# --- placement coordinates -------------------------------------------------


def test_placements_are_positioned_left_to_right_top_to_bottom():
    layout = pack_components(4, POKER, margin_in=0.5, gutter_in=0.1)
    p = layout.sheets[0].placements
    # data index is preserved in order
    assert [pl.index for pl in p] == [0, 1, 2, 3]
    # top-left anchored at the margin; pitch = size + gutter
    assert (p[0].x_in, p[0].y_in) == pytest.approx((0.5, 0.5))
    assert (p[1].x_in, p[1].y_in) == pytest.approx((0.5 + 2.6, 0.5))  # next column
    assert (p[2].x_in, p[2].y_in) == pytest.approx((0.5, 0.5 + 3.6))  # next row
    assert (p[3].x_in, p[3].y_in) == pytest.approx((0.5 + 2.6, 0.5 + 3.6))


def test_placement_carries_component_dimensions():
    p = pack_components(1, POKER).sheets[0].placements[0]
    assert (p.width_in, p.height_in) == (2.5, 3.5)


# --- filling multiple sheets -----------------------------------------------


def test_overflow_spills_onto_new_sheets_in_data_order():
    # 2x2 = 4 per page; 9 items -> 3 sheets (4, 4, 1).
    layout = pack_components(9, POKER, margin_in=0.5, gutter_in=0.1)
    assert [len(s.placements) for s in layout.sheets] == [4, 4, 1]
    # indices run 0..8 unbroken across the sheets, in order
    flat = [pl.index for s in layout.sheets for pl in s.placements]
    assert flat == list(range(9))
    # each new sheet restarts at the top-left margin
    assert (layout.sheets[1].placements[0].x_in,
            layout.sheets[1].placements[0].y_in) == pytest.approx((0.5, 0.5))


def test_zero_components_yields_no_sheets_but_still_reports_grid():
    layout = pack_components(0, POKER)
    assert layout.sheets == ()
    assert layout.columns >= 1 and layout.rows >= 1


# --- forced page breaks ----------------------------------------------------


def test_forced_page_break_starts_a_new_sheet():
    # 4 fit per page, but force item 2 onto a fresh sheet.
    layout = pack_components(5, POKER, margin_in=0.5, gutter_in=0.1,
                            page_breaks=[2])
    assert [len(s.placements) for s in layout.sheets] == [2, 3]
    assert layout.sheets[1].placements[0].index == 2
    # the item after a break resets to the top-left margin
    assert (layout.sheets[1].placements[0].x_in,
            layout.sheets[1].placements[0].y_in) == pytest.approx((0.5, 0.5))


def test_page_break_at_zero_is_a_noop():
    layout = pack_components(3, POKER, page_breaks=[0])
    assert len(layout.sheets) == 1


# --- error paths -----------------------------------------------------------


def test_component_too_wide_to_fit_raises():
    huge = ResolvedSize(9.0, 3.5, "rect")
    with pytest.raises(PackError, match="wide"):
        pack_components(1, huge, margin_in=0.5, gutter_in=0.1)


def test_component_too_tall_to_fit_raises():
    huge = ResolvedSize(2.5, 12.0, "rect")
    with pytest.raises(PackError, match="tall"):
        pack_components(1, huge, margin_in=0.5, gutter_in=0.1)


def test_margin_larger_than_page_raises():
    with pytest.raises(PackError):
        pack_components(1, POKER, margin_in=5.0, gutter_in=0.1)


def test_negative_count_raises():
    with pytest.raises(PackError):
        pack_components(-1, POKER)


def test_negative_margin_raises():
    with pytest.raises(PackError):
        pack_components(1, POKER, margin_in=-0.1)


def test_negative_gutter_raises():
    with pytest.raises(PackError):
        pack_components(1, POKER, gutter_in=-0.1)
