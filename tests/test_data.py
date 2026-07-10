"""Tests for the CSV data loader (task: Implement CSV data loader).

The loader turns a project's CSV into the shape the renderer consumes:
an ordered list of rows, one per component instance, each a mapping of
column header -> string value. These tests pin down that contract plus
the error handling a hand-edited or spreadsheet-exported CSV needs.
"""

import pytest

from prototyper.data import DataError, Dataset, load_data


def _write_csv(tmp_path, text):
    path = tmp_path / "cards.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_rows_as_dicts(tmp_path):
    path = _write_csv(
        tmp_path,
        "name,cost,type\nGuard,3,unit\nArcher,2,unit\n",
    )
    dataset = load_data(path)

    assert isinstance(dataset, Dataset)
    assert dataset.fieldnames == ("name", "cost", "type")
    assert dataset.rows == (
        {"name": "Guard", "cost": "3", "type": "unit"},
        {"name": "Archer", "cost": "2", "type": "unit"},
    )


def test_len_reports_row_count(tmp_path):
    path = _write_csv(tmp_path, "name\nA\nB\nC\n")
    assert len(load_data(path)) == 3


def test_values_are_always_strings(tmp_path):
    # CSV is untyped text; numeric-looking cells stay strings so the
    # template controls formatting.
    path = _write_csv(tmp_path, "cost\n10\n")
    assert load_data(path).rows[0]["cost"] == "10"


def test_headers_are_stripped(tmp_path):
    path = _write_csv(tmp_path, " name , cost \nGuard,3\n")
    assert load_data(path).fieldnames == ("name", "cost")


def test_values_are_not_stripped(tmp_path):
    # Leading/trailing whitespace in a value is preserved; only headers
    # (which become identifiers) are normalized.
    path = _write_csv(tmp_path, "name\n  spaced  \n")
    assert load_data(path).rows[0]["name"] == "  spaced  "


def test_short_rows_are_padded_with_empty_strings(tmp_path):
    # Spreadsheets often drop trailing empty cells; treat them as empty.
    path = _write_csv(tmp_path, "name,cost,type\nGuard,3\n")
    assert load_data(path).rows[0] == {"name": "Guard", "cost": "3", "type": ""}


def test_blank_lines_are_skipped(tmp_path):
    path = _write_csv(tmp_path, "name\nGuard\n\nArcher\n")
    assert load_data(path).rows == ({"name": "Guard"}, {"name": "Archer"})


def test_bom_is_stripped(tmp_path):
    # Excel writes a UTF-8 BOM; it must not leak into the first header.
    path = tmp_path / "cards.csv"
    path.write_text("﻿name,cost\nGuard,3\n", encoding="utf-8")
    assert load_data(path).fieldnames == ("name", "cost")


def test_utf8_values_preserved(tmp_path):
    path = _write_csv(tmp_path, "name\nGüard\n")
    assert load_data(path).rows[0]["name"] == "Güard"


def test_missing_file_raises(tmp_path):
    with pytest.raises(DataError, match="No data file"):
        load_data(tmp_path / "nope.csv")


def test_empty_file_raises(tmp_path):
    path = _write_csv(tmp_path, "")
    with pytest.raises(DataError, match="empty"):
        load_data(path)


def test_header_only_no_rows_raises(tmp_path):
    path = _write_csv(tmp_path, "name,cost\n")
    with pytest.raises(DataError, match="no data rows"):
        load_data(path)


def test_duplicate_headers_raise(tmp_path):
    path = _write_csv(tmp_path, "name,cost,name\nGuard,3,x\n")
    with pytest.raises(DataError, match="duplicate"):
        load_data(path)


def test_empty_header_name_raises(tmp_path):
    path = _write_csv(tmp_path, "name,,cost\nGuard,x,3\n")
    with pytest.raises(DataError, match="empty column header"):
        load_data(path)


def test_row_longer_than_header_raises(tmp_path):
    path = _write_csv(tmp_path, "name,cost\nGuard,3,extra\n")
    with pytest.raises(DataError, match="row 2"):
        load_data(path)
