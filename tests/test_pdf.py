"""Tests for PDF assembly from packed sheets (task: Implement PDF assembly
from packed sheets).

PDF assembly is the stage that turns the upstream pure-geometry results into
a real document: it takes a :class:`~prototyper.pack.PackedLayout` (which
sheet holds which component, and where), the already-rendered HTML for each
component (from :mod:`prototyper.render`), and optionally the cut lines for
each sheet (from :mod:`prototyper.cutlines`), and produces a multi-page
8.5x11 PDF.

The heavy lifting — building the single HTML/CSS document that WeasyPrint
paints — is kept pure and separately testable in ``build_document_html`` so
it can be verified without WeasyPrint's native (Pango/Cairo/GObject)
libraries installed. Only ``assemble_pdf`` touches WeasyPrint, imported
lazily, so tests that need a real PDF skip cleanly where those libraries are
absent.
"""

import re

import pytest

from prototyper.cutlines import CutLine, cut_lines_for_layout
from prototyper.pack import PackedLayout, Placement, Sheet, pack_components
from prototyper.pdf import (
    DEFAULT_CUT_LINE_STYLE,
    CutLineStyle,
    PdfError,
    assemble_pdf,
    build_document_html,
)
from prototyper.sizing import ResolvedSize


POKER = ResolvedSize(2.5, 3.5, "rect")


def _layout(count, **kwargs):
    return pack_components(count, POKER, **kwargs)


def _components(n):
    return [f"<p>card {i}</p>" for i in range(n)]


# --- document structure ----------------------------------------------------


def test_document_is_wellformed_html():
    html = build_document_html(_layout(1), _components(1))
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert 'charset="utf-8"' in html


def test_page_size_matches_layout():
    html = build_document_html(_layout(1), _components(1))
    assert "@page" in html
    assert "size: 8.5in 11in" in html


def test_page_size_reflects_custom_page_dimensions():
    layout = pack_components(
        1, POKER, page_width_in=6.0, page_height_in=9.0
    )
    html = build_document_html(layout, _components(1))
    assert "size: 6in 9in" in html


def test_one_sheet_div_per_sheet():
    # 4 poker per page with defaults -> 5 components spill onto 2 sheets.
    layout = _layout(5)
    assert len(layout.sheets) == 2
    html = build_document_html(layout, _components(5))
    assert html.count('class="sheet"') == 2


def test_sheets_break_between_pages_but_not_after_the_last():
    # The sibling-combinator break-before idiom avoids a trailing blank page.
    html = build_document_html(_layout(5), _components(5))
    assert ".sheet + .sheet" in html
    assert "break-before: page" in html


def test_empty_layout_has_no_sheet_divs():
    html = build_document_html(_layout(0), _components(0))
    assert len(_layout(0).sheets) == 0
    assert 'class="sheet"' not in html
    # Still a valid, paintable (blank) document.
    assert "<html" in html and "@page" in html


# --- component placement ---------------------------------------------------


def test_component_positioned_at_its_placement():
    layout = _layout(1)
    placement = layout.sheets[0].placements[0]
    html = build_document_html(layout, _components(1))
    # The component div carries its trim-box geometry, in inches.
    assert f"left: {placement.x_in:g}in" in html
    assert f"top: {placement.y_in:g}in" in html
    assert "width: 2.5in" in html
    assert "height: 3.5in" in html


def test_component_html_is_embedded_verbatim():
    html = build_document_html(_layout(3), ["<b>A</b>", "<i>B</i>", "<u>C</u>"])
    assert "<b>A</b>" in html
    assert "<i>B</i>" in html
    assert "<u>C</u>" in html


def test_components_mapped_by_data_index_across_sheets():
    # Second sheet's sole component is data index 4 -> components[4].
    layout = _layout(5)
    assert layout.sheets[1].placements[0].index == 4
    parts = _components(5)
    html = build_document_html(layout, parts)
    # Split on the sheet boundary and confirm card 4 lands on the 2nd sheet.
    first, second = html.split('class="sheet"')[1:3]
    assert "card 4" in second
    assert "card 4" not in first


def test_missing_component_for_placement_raises():
    with pytest.raises(PdfError, match="no rendered component"):
        build_document_html(_layout(3), _components(2))


# --- cut lines -------------------------------------------------------------


def test_no_cut_lines_by_default():
    html = build_document_html(_layout(4), _components(4))
    assert 'class="cut-line"' not in html


def test_cut_lines_rendered_when_provided():
    layout = _layout(4)
    cut_lines = cut_lines_for_layout(layout)
    html = build_document_html(layout, _components(4), cut_lines=cut_lines)
    n_lines = sum(len(sheet) for sheet in cut_lines)
    assert n_lines > 0
    assert html.count('class="cut-line"') == n_lines


def test_vertical_and_horizontal_cut_lines_use_the_right_border():
    sheet_lines = (
        CutLine(1.0, 0.0, 1.0, 11.0, "vertical"),
        CutLine(0.0, 2.0, 8.5, 2.0, "horizontal"),
    )
    html = build_document_html(
        _layout(1), _components(1), cut_lines=(sheet_lines,)
    )
    assert "border-left:" in html  # vertical line
    assert "border-top:" in html  # horizontal line
    assert "left: 1in" in html
    assert "top: 2in" in html


def test_default_cut_line_style_applied():
    layout = _layout(1)
    cut_lines = cut_lines_for_layout(layout)
    html = build_document_html(layout, _components(1), cut_lines=cut_lines)
    assert DEFAULT_CUT_LINE_STYLE.color in html
    assert f"{DEFAULT_CUT_LINE_STYLE.width_pt:g}pt" in html


def test_custom_cut_line_style_applied():
    layout = _layout(1)
    cut_lines = cut_lines_for_layout(layout)
    style = CutLineStyle(width_pt=1.0, color="#ff0000", css_style="dashed")
    html = build_document_html(
        layout, _components(1), cut_lines=cut_lines, cut_line_style=style
    )
    assert "#ff0000" in html
    assert "dashed" in html
    assert "1pt" in html


def test_cut_lines_length_must_match_sheet_count():
    layout = _layout(5)  # 2 sheets
    with pytest.raises(PdfError, match="cut line"):
        build_document_html(layout, _components(5), cut_lines=(( ),))


# --- assemble_pdf ----------------------------------------------------------


def test_assemble_pdf_validates_before_touching_weasyprint(tmp_path):
    # Validation happens in build_document_html, which runs before the lazy
    # WeasyPrint import, so a bad layout raises PdfError even where the
    # native libraries are unavailable.
    out = tmp_path / "out.pdf"
    with pytest.raises(PdfError):
        assemble_pdf(_layout(3), _components(2), out)
    assert not out.exists()


def _weasyprint_or_skip():
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:  # OSError (missing native libs) or ImportError
        pytest.skip(f"weasyprint unavailable in this environment: {exc}")
    return weasyprint


def test_assemble_pdf_writes_a_real_pdf(tmp_path):
    _weasyprint_or_skip()
    layout = _layout(5)
    out = tmp_path / "deck.pdf"
    result = assemble_pdf(
        layout,
        _components(5),
        out,
        cut_lines=cut_lines_for_layout(layout),
    )
    assert result == out
    assert out.exists()
    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(data) > 1000
