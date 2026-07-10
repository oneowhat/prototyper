"""Tests for the project.yaml schema and loader (task: Define project.yaml
schema and loader).

These cover the shape the rest of the pipeline depends on: a validated,
path-resolved ``ProjectConfig`` object, sensible layout defaults, and
clear errors for malformed or incomplete configs.
"""

import textwrap

import pytest

from prototyper.config import (
    ComponentSize,
    ConfigError,
    Layout,
    ProjectConfig,
    load_project,
)


def _write_project(tmp_path, yaml_text):
    (tmp_path / "project.yaml").write_text(textwrap.dedent(yaml_text))
    return tmp_path


def test_load_valid_preset_project(tmp_path):
    _write_project(
        tmp_path,
        """
        name: My Game
        component:
          size: poker
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    config = load_project(tmp_path)

    assert isinstance(config, ProjectConfig)
    assert config.name == "My Game"
    assert config.project_dir == tmp_path.resolve()
    # Paths are resolved relative to the project directory.
    assert config.data_path == (tmp_path / "data/cards.csv").resolve()
    assert config.template_path == (tmp_path / "templates/card.html").resolve()
    assert config.component == ComponentSize(preset="poker", width=None, height=None)


def test_load_custom_size_project(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          width: 2.5in
          height: 3.5in
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    config = load_project(tmp_path)

    assert config.component == ComponentSize(
        preset=None, width="2.5in", height="3.5in"
    )
    # name defaults to the project directory name when omitted.
    assert config.name == tmp_path.name


def test_layout_defaults_applied(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    config = load_project(tmp_path)

    assert config.layout == Layout(margin="0.5in", gutter="0.1in", cut_lines=True)


def test_layout_overrides_respected(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
        data: data/cards.csv
        template: templates/card.html
        layout:
          margin: 0.25in
          gutter: 0.2in
          cut_lines: false
        """,
    )
    config = load_project(tmp_path)

    assert config.layout == Layout(margin="0.25in", gutter="0.2in", cut_lines=False)


def test_accepts_path_to_yaml_file_directly(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    config = load_project(tmp_path / "project.yaml")
    assert config.project_dir == tmp_path.resolve()


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="project.yaml"):
        load_project(tmp_path)


def test_missing_component_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    with pytest.raises(ConfigError, match="component"):
        load_project(tmp_path)


def test_missing_data_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
        template: templates/card.html
        """,
    )
    with pytest.raises(ConfigError, match="data"):
        load_project(tmp_path)


def test_missing_template_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
        data: data/cards.csv
        """,
    )
    with pytest.raises(ConfigError, match="template"):
        load_project(tmp_path)


def test_component_without_size_or_dimensions_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        component: {}
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    with pytest.raises(ConfigError, match="size"):
        load_project(tmp_path)


def test_component_with_partial_dimensions_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          width: 2.5in
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    with pytest.raises(ConfigError, match="height"):
        load_project(tmp_path)


def test_component_preset_and_dimensions_conflict_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
          width: 2.5in
          height: 3.5in
        data: data/cards.csv
        template: templates/card.html
        """,
    )
    with pytest.raises(ConfigError, match="both"):
        load_project(tmp_path)


def test_invalid_yaml_raises(tmp_path):
    (tmp_path / "project.yaml").write_text("component: [unclosed\n")
    with pytest.raises(ConfigError, match="parse"):
        load_project(tmp_path)


def test_top_level_not_mapping_raises(tmp_path):
    (tmp_path / "project.yaml").write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_project(tmp_path)


def test_unknown_top_level_key_raises(tmp_path):
    _write_project(
        tmp_path,
        """
        component:
          size: poker
        data: data/cards.csv
        template: templates/card.html
        colour: blue
        """,
    )
    with pytest.raises(ConfigError, match="colour"):
        load_project(tmp_path)
