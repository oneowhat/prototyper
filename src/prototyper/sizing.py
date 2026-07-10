"""Component size resolution: presets and custom dimensions.

The config loader (:mod:`prototyper.config`) captures a component's size
*verbatim* — either a named ``preset`` or a raw ``width``/``height`` pair
of strings — and deliberately leaves preset lookup and unit parsing to
this module. Here we turn that loosely-typed :class:`~prototyper.config.ComponentSize`
into a concrete :class:`ResolvedSize` with numeric dimensions the page
packing and rendering stages can compute with.

Dimensions are canonicalised to **inches** (as floats): the output page is
8.5x11 inches, so inches are the tool's native unit and the natural basis
for grid-packing math. CSS-style length units (``in``, ``mm``, ``cm``,
``pt``, ``px``, ``pc``) are accepted for custom sizes and converted; a bare
number is taken to mean inches.

Consistent with the config/data loaders' "fail loud on anything that
silently ruins a print run" stance, an unknown preset, an unparseable
length, an unknown unit, or a non-positive dimension all raise
:class:`SizeError` with a human-readable message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ComponentSize


class SizeError(Exception):
    """Raised when a component size can't be resolved to real dimensions."""


@dataclass(frozen=True)
class ResolvedSize:
    """A component's concrete size in inches, plus its trim shape.

    ``width_in``/``height_in`` are the trim (finished) dimensions of one
    component in inches. ``shape`` is the outline used downstream for cut
    lines and packing — ``"rect"`` for cards and rectangular/square tokens,
    ``"hex"`` for hexagonal tokens. Custom sizes are always rectangular;
    non-rectangular outlines come only from presets.
    """

    width_in: float
    height_in: float
    shape: str = "rect"


# Standard component presets, keyed by their canonical (normalised) name.
# Values are (width_in, height_in, shape). The card sizes are the industry
# standards designers expect; token sizes are common home-print defaults.
_PRESETS: dict[str, ResolvedSize] = {
    "poker": ResolvedSize(2.5, 3.5, "rect"),
    "bridge": ResolvedSize(2.25, 3.5, "rect"),
    "tarot": ResolvedSize(2.75, 4.75, "rect"),
    "mini": ResolvedSize(1.75, 2.5, "rect"),
    "hex-token": ResolvedSize(1.0, 1.0, "hex"),
    "square-token": ResolvedSize(1.0, 1.0, "rect"),
}

# Inches per unit, for the CSS-style absolute length units we accept.
_UNITS_PER_INCH: dict[str, float] = {
    "in": 1.0,
    "mm": 1.0 / 25.4,
    "cm": 1.0 / 2.54,
    "pt": 1.0 / 72.0,  # CSS/PDF point
    "pc": 1.0 / 6.0,  # pica = 12pt
    "px": 1.0 / 96.0,  # CSS reference pixel
}

# A length is a number (int or float, optional leading sign) followed by an
# optional unit; surrounding whitespace is tolerated.
_LENGTH_RE = re.compile(r"^\s*([+-]?\d*\.?\d+)\s*([a-zA-Z]*)\s*$")


def _normalise_preset(name: str) -> str:
    """Canonicalise a preset name: lowercase, hyphen-separated, trimmed."""
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def list_presets() -> tuple[str, ...]:
    """Return the available preset names, in alphabetical order."""
    return tuple(sorted(_PRESETS))


def parse_length(text: str, *, field: str = "length") -> float:
    """Parse a CSS-style length string into inches.

    Accepts a number with an optional unit (``in``, ``mm``, ``cm``, ``pt``,
    ``pc``, ``px``); a bare number is interpreted as inches. ``field`` names
    the dimension in error messages. Raises :class:`SizeError` if the value
    can't be parsed, uses an unknown unit, or is not strictly positive.
    """
    if not isinstance(text, str):
        raise SizeError(f"{field} must be a string, got {type(text).__name__}")

    match = _LENGTH_RE.match(text)
    if not match:
        raise SizeError(f"{field} {text!r} is not a valid length")

    number, unit = match.groups()
    try:
        value = float(number)
    except ValueError:  # pragma: no cover - regex already constrains number
        raise SizeError(f"{field} {text!r} is not a valid length") from None

    unit = unit.lower() or "in"
    if unit not in _UNITS_PER_INCH:
        allowed = ", ".join(sorted(_UNITS_PER_INCH))
        raise SizeError(
            f"{field} {text!r} uses unknown unit {unit!r}; allowed units: {allowed}"
        )

    inches = value * _UNITS_PER_INCH[unit]
    if inches <= 0:
        raise SizeError(f"{field} must be positive, got {text!r}")
    return inches


def resolve_preset(name: str) -> ResolvedSize:
    """Resolve a preset name to its :class:`ResolvedSize`.

    Names are matched case-insensitively and ignore ``-``/``_``/space
    differences (``"Hex Token"`` == ``"hex-token"``). Raises
    :class:`SizeError` listing the available presets if unknown.
    """
    key = _normalise_preset(name)
    if key not in _PRESETS:
        available = ", ".join(list_presets())
        raise SizeError(f"unknown size preset {name!r}; available presets: {available}")
    return _PRESETS[key]


def resolve_size(component: ComponentSize) -> ResolvedSize:
    """Resolve a :class:`~prototyper.config.ComponentSize` to real dimensions.

    A preset is looked up; a custom width/height pair is parsed and unit-
    converted to inches (yielding a rectangular shape). Raises
    :class:`SizeError` if the component specifies neither, or if any part
    fails to resolve.
    """
    if component.preset is not None:
        return resolve_preset(component.preset)

    if component.width is None or component.height is None:
        raise SizeError(
            "component has no size: expected a preset or a width/height pair"
        )

    width_in = parse_length(component.width, field="width")
    height_in = parse_length(component.height, field="height")
    return ResolvedSize(width_in=width_in, height_in=height_in, shape="rect")
