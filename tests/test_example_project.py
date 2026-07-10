"""The shipped example starter project must load and build out of the box.

This guards the PRD's "a first project works with minimal configuration"
goal: the example under ``examples/`` is the thing a new designer copies
and runs first, so it must stay a valid, buildable project. The test drives
it through :func:`prototyper.build.plan_build` (the pure planning pipeline)
so it exercises config -> data -> sizing -> pack -> render -> cutlines
without needing WeasyPrint's native libraries.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from prototyper.build import plan_build
from prototyper.config import load_project
from prototyper.data import load_data

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "starter-cards"


def test_example_directory_follows_the_folder_convention():
    assert (EXAMPLE_DIR / "project.yaml").is_file()
    assert (EXAMPLE_DIR / "data" / "cards.csv").is_file()
    assert (EXAMPLE_DIR / "templates" / "card.html").is_file()
    assert (EXAMPLE_DIR / "README.md").is_file()


def test_example_config_loads_and_resolves_paths():
    config = load_project(EXAMPLE_DIR)
    assert config.data_path.is_file()
    assert config.template_path.is_file()
    # Cut lines on by default is the home-printing-friendly starting point.
    assert config.layout.cut_lines is True


def test_example_builds_a_multi_sheet_plan():
    config = load_project(EXAMPLE_DIR)
    dataset = load_data(config.data_path)

    plan = plan_build(EXAMPLE_DIR)

    # One rendered component per data row, in data order.
    assert len(plan.components) == len(dataset)
    # Enough cards to spill onto more than one sheet, so the example
    # actually demonstrates pagination/packing.
    assert len(plan.layout.sheets) >= 2
    # Cut lines are computed (one tuple per sheet) since the layout enables them.
    assert plan.cut_lines is not None
    assert len(plan.cut_lines) == len(plan.layout.sheets)


def test_example_template_substitutes_data_values():
    config = load_project(EXAMPLE_DIR)
    dataset = load_data(config.data_path)
    plan = plan_build(EXAMPLE_DIR)

    # The first card's name should appear in the first rendered component.
    first_name = dataset.rows[0]["name"]
    assert first_name in plan.components[0]


def test_example_csv_headers_match_template_placeholders():
    # Every column the template references must exist in the CSV, otherwise
    # StrictUndefined would make the render (and thus the example) fail.
    config = load_project(EXAMPLE_DIR)
    with config.data_path.open(newline="", encoding="utf-8-sig") as fh:
        headers = set(next(csv.reader(fh)))
    assert {"name", "cost", "type", "text"} <= headers
