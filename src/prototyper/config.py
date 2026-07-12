"""Project configuration: the ``project.yaml`` schema and its loader.

``project.yaml`` is the file that ties a project together (see the PRD's
"Project folder convention"). This module defines its schema as a set of
frozen dataclasses and a :func:`load_project` loader that parses,
validates, and path-resolves it into a :class:`ProjectConfig`.

Scope note: this loader validates *structure* only. It resolves the data
and template paths against the project directory but does not require the
files to exist yet (that is the job of the CSV/template loaders), and it
does not resolve size presets or parse dimension units into numbers
(that belongs to the component-sizing task). Component size is captured
verbatim so those later steps have something well-formed to work from.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_FILENAME = "project.yaml"

# Layout defaults. Home-printing friendly: a half-inch margin keeps clear
# of typical printer no-print borders, a small gutter leaves room for
# scissor/cutter trimming, and cut lines are on by default per the PRD.
DEFAULT_MARGIN = "0.5in"
DEFAULT_GUTTER = "0.1in"
DEFAULT_CUT_LINES = True

_ALLOWED_TOP_LEVEL = {"name", "component", "data", "template", "layout"}
_ALLOWED_COMPONENT = {"size", "width", "height"}
_ALLOWED_LAYOUT = {"margin", "gutter", "cut_lines"}


class ConfigError(Exception):
    """Raised when a project.yaml is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class ComponentSize:
    """How big a single component is.

    Either a named ``preset`` (resolved to real dimensions later) or an
    explicit ``width``/``height`` pair, never both. Dimensions are kept
    as raw strings (e.g. ``"2.5in"``); unit parsing happens downstream.
    """

    preset: str | None = None
    width: str | None = None
    height: str | None = None


@dataclass(frozen=True)
class Layout:
    """Page layout hints (margins, gutter, cut lines)."""

    margin: str = DEFAULT_MARGIN
    gutter: str = DEFAULT_GUTTER
    cut_lines: bool = DEFAULT_CUT_LINES


@dataclass(frozen=True)
class ProjectConfig:
    """A fully validated, path-resolved project configuration."""

    name: str
    project_dir: Path
    data_path: Path
    template_path: Path
    component: ComponentSize
    layout: Layout


def _resolve_config_path(path: Path) -> tuple[Path, Path]:
    """Return ``(config_file, project_dir)`` for a dir or a yaml file path."""
    if path.is_dir():
        return path / CONFIG_FILENAME, path
    # Treat anything else as the config file itself (it may not exist yet).
    return path, path.parent


def _require_str(mapping: dict, key: str, where: str) -> str:
    value = mapping.get(key)
    if value is None:
        raise ConfigError(f"{where} is missing required key '{key}'")
    if not isinstance(value, str):
        raise ConfigError(f"{where} key '{key}' must be a string, got {type(value).__name__}")
    return value


def _reject_unknown(mapping: dict, allowed: set[str], where: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        allowed_names = ", ".join(sorted(allowed))
        raise ConfigError(f"{where} has unknown key(s): {names}. Allowed: {allowed_names}")


def _parse_component(raw: object) -> ComponentSize:
    if raw is None:
        raise ConfigError("project.yaml is missing required key 'component'")
    if not isinstance(raw, dict):
        raise ConfigError("'component' must be a mapping")
    _reject_unknown(raw, _ALLOWED_COMPONENT, "'component'")

    preset = raw.get("size")
    width = raw.get("width")
    height = raw.get("height")

    has_dims = width is not None or height is not None
    if preset is not None and has_dims:
        raise ConfigError(
            "'component' cannot set both a 'size' preset and explicit "
            "width/height; choose one"
        )
    if preset is None and not has_dims:
        raise ConfigError(
            "'component' must set either a 'size' preset or both 'width' "
            "and 'height'"
        )
    if has_dims:
        if width is None:
            raise ConfigError("'component' sets 'height' but is missing 'width'")
        if height is None:
            raise ConfigError("'component' sets 'width' but is missing 'height'")

    def _as_str(value, field):
        if value is None:
            return None
        if not isinstance(value, (str, int, float)):
            raise ConfigError(f"'component.{field}' must be a string or number")
        return str(value)

    return ComponentSize(
        preset=_as_str(preset, "size"),
        width=_as_str(width, "width"),
        height=_as_str(height, "height"),
    )


def _parse_layout(raw: object) -> Layout:
    if raw is None:
        return Layout()
    if not isinstance(raw, dict):
        raise ConfigError("'layout' must be a mapping")
    _reject_unknown(raw, _ALLOWED_LAYOUT, "'layout'")

    def _as_str(value, field, default):
        if value is None:
            return default
        if not isinstance(value, (str, int, float)):
            raise ConfigError(f"'layout.{field}' must be a string or number")
        return str(value)

    cut_lines = raw.get("cut_lines", DEFAULT_CUT_LINES)
    if not isinstance(cut_lines, bool):
        raise ConfigError("'layout.cut_lines' must be true or false")

    return Layout(
        margin=_as_str(raw.get("margin"), "margin", DEFAULT_MARGIN),
        gutter=_as_str(raw.get("gutter"), "gutter", DEFAULT_GUTTER),
        cut_lines=cut_lines,
    )


def load_project(path: str | Path) -> ProjectConfig:
    """Load and validate a project.

    ``path`` may be a project directory (containing ``project.yaml``) or a
    path to the ``project.yaml`` file directly. Relative ``data`` and
    ``template`` paths are resolved against the project directory.

    Raises :class:`ConfigError` for any missing file, parse failure, or
    schema violation.
    """
    config_file, project_dir = _resolve_config_path(Path(path))

    if not config_file.is_file():
        raise ConfigError(f"No {CONFIG_FILENAME} found at {config_file}")

    try:
        raw = yaml.safe_load(config_file.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {config_file}: {exc}") from exc

    if raw is None:
        raise ConfigError(f"{config_file} is empty")
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_file} must contain a top-level mapping")
    _reject_unknown(raw, _ALLOWED_TOP_LEVEL, "project.yaml")

    component = _parse_component(raw.get("component"))
    data_rel = _require_str(raw, "data", "project.yaml")
    template_rel = _require_str(raw, "template", "project.yaml")
    layout = _parse_layout(raw.get("layout"))

    project_dir = project_dir.resolve()
    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        raise ConfigError("'name' must be a string")
    if not name:
        name = project_dir.name

    return ProjectConfig(
        name=name,
        project_dir=project_dir,
        data_path=(project_dir / data_rel).resolve(),
        template_path=(project_dir / template_rel).resolve(),
        component=component,
        layout=layout,
    )
