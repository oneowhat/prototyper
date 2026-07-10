"""Tests for component size resolution (task: Implement component size
presets and custom sizing).

The config loader captures a component's size verbatim — a preset name
*xor* a width/height pair of raw strings. This module turns that into
concrete numeric dimensions (canonicalised to inches) that the page
packing and rendering stages can compute with, resolving named presets
and parsing CSS-style length units.
"""

import pytest

from prototyper.config import ComponentSize
from prototyper.sizing import (
    ResolvedSize,
    SizeError,
    list_presets,
    parse_length,
    resolve_size,
)


# --- presets ---------------------------------------------------------------


def test_poker_preset_resolves_to_standard_dimensions():
    size = resolve_size(ComponentSize(preset="poker"))
    assert size == ResolvedSize(width_in=2.5, height_in=3.5, shape="rect")


def test_bridge_and_tarot_presets():
    assert resolve_size(ComponentSize(preset="bridge")) == ResolvedSize(2.25, 3.5, "rect")
    assert resolve_size(ComponentSize(preset="tarot")) == ResolvedSize(2.75, 4.75, "rect")


def test_hex_token_preset_carries_hex_shape():
    size = resolve_size(ComponentSize(preset="hex-token"))
    assert size.shape == "hex"
    assert size.width_in > 0 and size.height_in > 0


def test_square_token_preset():
    size = resolve_size(ComponentSize(preset="square-token"))
    assert size.width_in == size.height_in


def test_preset_name_is_normalised():
    # Case, surrounding whitespace, and space/underscore separators are all
    # treated the same as the canonical hyphenated lowercase name.
    a = resolve_size(ComponentSize(preset="Poker"))
    b = resolve_size(ComponentSize(preset="  poker  "))
    assert a == b == ResolvedSize(2.5, 3.5, "rect")

    hexed = resolve_size(ComponentSize(preset="hex token"))
    hexed2 = resolve_size(ComponentSize(preset="HEX_TOKEN"))
    assert hexed == hexed2
    assert hexed.shape == "hex"


def test_list_presets_includes_prd_examples():
    presets = list_presets()
    for name in ("poker", "bridge", "tarot", "hex-token", "square-token"):
        assert name in presets


def test_unknown_preset_raises_and_lists_options():
    with pytest.raises(SizeError, match="poker"):
        resolve_size(ComponentSize(preset="jumbo"))


# --- custom sizing ---------------------------------------------------------


def test_custom_inch_dimensions():
    size = resolve_size(ComponentSize(width="2.5in", height="3.5in"))
    assert size == ResolvedSize(2.5, 3.5, "rect")


def test_custom_millimetres_convert_to_inches():
    size = resolve_size(ComponentSize(width="63.5mm", height="88.9mm"))
    assert size.width_in == pytest.approx(2.5)
    assert size.height_in == pytest.approx(3.5)


def test_custom_centimetres_convert():
    size = resolve_size(ComponentSize(width="2.54cm", height="5.08cm"))
    assert size.width_in == pytest.approx(1.0)
    assert size.height_in == pytest.approx(2.0)


def test_points_and_pixels_convert():
    assert parse_length("72pt") == pytest.approx(1.0)
    assert parse_length("96px") == pytest.approx(1.0)


def test_bare_number_defaults_to_inches():
    assert parse_length("2.5") == pytest.approx(2.5)
    # The config loader stringifies numeric YAML values, so a plain number
    # arrives here as its string form.
    size = resolve_size(ComponentSize(width="2", height="3"))
    assert size == ResolvedSize(2.0, 3.0, "rect")


def test_whitespace_and_case_in_units_tolerated():
    assert parse_length("  2.5 IN ") == pytest.approx(2.5)


# --- error paths -----------------------------------------------------------


def test_unparseable_length_raises():
    with pytest.raises(SizeError, match="width"):
        resolve_size(ComponentSize(width="wide", height="3.5in"))


def test_unknown_unit_raises():
    with pytest.raises(SizeError, match="furlong"):
        parse_length("2furlong")


def test_zero_dimension_raises():
    with pytest.raises(SizeError, match="positive"):
        parse_length("0in")


def test_negative_dimension_raises():
    with pytest.raises(SizeError, match="positive"):
        resolve_size(ComponentSize(width="-2.5in", height="3.5in"))


def test_empty_component_raises():
    with pytest.raises(SizeError):
        resolve_size(ComponentSize())
