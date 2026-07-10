"""CSV data loader: one project CSV -> an ordered list of component rows.

The PRD's input model is "CSV, one row per component instance; column
headers map to template placeholders". This module reads that CSV into a
:class:`Dataset` — the ordered ``fieldnames`` plus the ``rows`` (each a
``{header: value}`` mapping) that the renderer instantiates one component
per. Every value is kept as a string: CSV is untyped text and the
template decides how to format it.

The loader is deliberately strict about the things that silently corrupt
a print run — duplicate or blank headers (ambiguous placeholder
mapping), rows with more columns than the header (misaligned data), and
files with no data rows (nothing to build) — while being forgiving about
the things spreadsheets do harmlessly: a leading UTF-8 BOM, trailing
empty cells, and blank lines.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class DataError(Exception):
    """Raised when a data CSV is missing, empty, or malformed."""


@dataclass(frozen=True)
class Dataset:
    """A validated CSV: ordered column names and their string-valued rows."""

    fieldnames: tuple[str, ...]
    rows: tuple[dict[str, str], ...]

    def __len__(self) -> int:
        return len(self.rows)


def _validate_header(header: list[str], where: Path) -> tuple[str, ...]:
    names = [name.strip() for name in header]
    if any(name == "" for name in names):
        raise DataError(f"{where}: empty column header (blank column name)")
    seen: set[str] = set()
    duplicates = {name for name in names if name in seen or seen.add(name)}
    if duplicates:
        listed = ", ".join(sorted(duplicates))
        raise DataError(f"{where}: duplicate column header(s): {listed}")
    return tuple(names)


def load_data(path: str | Path) -> Dataset:
    """Load and validate a project's component CSV.

    Returns a :class:`Dataset` of ordered ``fieldnames`` and ``rows``,
    one row per component instance. Raises :class:`DataError` for a
    missing file, an empty file, a file with headers but no data rows, or
    any structural problem in the header or a row.
    """
    path = Path(path)
    if not path.is_file():
        raise DataError(f"No data file found at {path}")

    # utf-8-sig transparently strips the BOM that Excel prepends; newline=""
    # lets the csv module handle embedded newlines in quoted fields.
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                raise DataError(f"{path}: data file is empty; expected a header row") from None

            fieldnames = _validate_header(header, path)

            rows: list[dict[str, str]] = []
            # Line 1 is the header, so data rows start at line 2.
            for lineno, raw in enumerate(reader, start=2):
                if not raw or all(cell == "" for cell in raw):
                    continue  # blank line
                if len(raw) > len(fieldnames):
                    raise DataError(
                        f"{path}: row {lineno} has more columns "
                        f"({len(raw)}) than the header ({len(fieldnames)})"
                    )
                # Pad short rows: a spreadsheet often drops trailing empties.
                padded = list(raw) + [""] * (len(fieldnames) - len(raw))
                rows.append(dict(zip(fieldnames, padded)))
    except UnicodeDecodeError as exc:
        raise DataError(f"{path}: file is not valid UTF-8 text: {exc}") from exc

    if not rows:
        raise DataError(f"{path}: has a header but no data rows")

    return Dataset(fieldnames=fieldnames, rows=tuple(rows))
