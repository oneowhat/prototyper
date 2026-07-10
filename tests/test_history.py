"""Tests for the design-memory history log (task: Implement history log with
automatic build entries).

The PRD's "Design memory" calls for a single tool-managed log at
``.prototyper/history.yaml`` where every ``build`` run appends an automatic
entry capturing at minimum a timestamp, a content hash of the
template/data/config inputs, and the output PDF path. This module's job is
that log and the automatic build entry; the manual ``note`` command is a
separate later task, so the format is kept a flat, forward-compatible list of
typed entries.

These tests exercise the log directly (no WeasyPrint needed); the one test of
``run_build`` wiring stubs the PDF write so it runs without WeasyPrint's
native libraries.
"""

import textwrap

import pytest

from prototyper import history
from prototyper.config import load_project
from prototyper.history import (
    HistoryError,
    hash_inputs,
    history_path,
    load_history,
    record_build,
)


def _make_project(root, *, data="name\nCard 0\n", template="<div>{{ name }}</div>"):
    (root / "data").mkdir()
    (root / "templates").mkdir()
    (root / "data" / "cards.csv").write_text(data)
    (root / "templates" / "card.html").write_text(template)
    (root / "project.yaml").write_text(
        textwrap.dedent(
            """\
            name: my-deck
            component:
              size: poker
            data: data/cards.csv
            template: templates/card.html
            """
        )
    )
    return load_project(root)


# --- input hashing ---------------------------------------------------------


def test_hash_inputs_is_stable(tmp_path):
    config = _make_project(tmp_path)
    assert hash_inputs(config) == hash_inputs(config)


def test_hash_inputs_is_prefixed(tmp_path):
    config = _make_project(tmp_path)
    assert hash_inputs(config).startswith("sha256:")


def test_hash_inputs_changes_with_template(tmp_path):
    before = hash_inputs(_make_project(tmp_path))
    (tmp_path / "templates" / "card.html").write_text("<p>{{ name }}</p>")
    after = hash_inputs(load_project(tmp_path))
    assert before != after


def test_hash_inputs_changes_with_data(tmp_path):
    before = hash_inputs(_make_project(tmp_path))
    (tmp_path / "data" / "cards.csv").write_text("name\nCard 0\nCard 1\n")
    after = hash_inputs(load_project(tmp_path))
    assert before != after


def test_hash_inputs_changes_with_config(tmp_path):
    before = hash_inputs(_make_project(tmp_path))
    (tmp_path / "project.yaml").write_text(
        textwrap.dedent(
            """\
            name: my-deck
            component:
              size: tarot
            data: data/cards.csv
            template: templates/card.html
            """
        )
    )
    after = hash_inputs(load_project(tmp_path))
    assert before != after


def test_hash_inputs_missing_file_raises(tmp_path):
    config = _make_project(tmp_path)
    (tmp_path / "data" / "cards.csv").unlink()
    with pytest.raises(HistoryError):
        hash_inputs(config)


# --- reading an empty / missing log ----------------------------------------


def test_history_path_location(tmp_path):
    config = _make_project(tmp_path)
    path = history_path(config.project_dir)
    assert path == config.project_dir / ".prototyper" / "history.yaml"


def test_load_history_missing_is_empty(tmp_path):
    config = _make_project(tmp_path)
    assert load_history(config.project_dir) == ()


# --- recording build entries -----------------------------------------------


def test_record_build_creates_log_and_entry(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "build" / "my-deck.pdf",
                 components=1, sheets=1)

    assert history_path(config.project_dir).is_file()
    entries = load_history(config.project_dir)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["type"] == "build"
    assert entry["inputs_hash"] == hash_inputs(config)
    assert entry["components"] == 1
    assert entry["sheets"] == 1
    # Required PRD fields present and non-empty.
    assert entry["timestamp"]
    assert entry["output"]


def test_record_build_stores_output_relative_to_project(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "build" / "my-deck.pdf",
                 components=1, sheets=1)
    entry = load_history(config.project_dir)[0]
    assert entry["output"] == "build/my-deck.pdf"


def test_record_build_keeps_absolute_output_outside_project(tmp_path):
    config = _make_project(tmp_path)
    outside = tmp_path.parent / "elsewhere.pdf"
    record_build(config, outside, components=1, sheets=1)
    entry = load_history(config.project_dir)[0]
    assert entry["output"] == str(outside.resolve())


def test_record_build_uses_explicit_timestamp(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "out.pdf",
                 components=1, sheets=1, timestamp="2026-07-10T00:00:00+00:00")
    entry = load_history(config.project_dir)[0]
    assert entry["timestamp"] == "2026-07-10T00:00:00+00:00"


def test_record_build_appends_in_order(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T00:00:00+00:00")
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T01:00:00+00:00")
    entries = load_history(config.project_dir)
    assert [e["timestamp"] for e in entries] == [
        "2026-07-10T00:00:00+00:00",
        "2026-07-10T01:00:00+00:00",
    ]


def test_history_is_human_readable_yaml(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "build" / "my-deck.pdf",
                 components=2, sheets=1, timestamp="2026-07-10T00:00:00+00:00")
    text = history_path(config.project_dir).read_text()
    # A designer can open it and read the entry as a changelog.
    assert "type: build" in text
    assert "timestamp:" in text
    # Keys are in a logical (declared) order, not alphabetised.
    assert text.index("type:") < text.index("timestamp:") < text.index("inputs_hash:")


# --- malformed log ---------------------------------------------------------


def test_load_history_rejects_non_mapping(tmp_path):
    config = _make_project(tmp_path)
    path = history_path(config.project_dir)
    path.parent.mkdir(parents=True)
    path.write_text("- just a list\n")
    with pytest.raises(HistoryError):
        load_history(config.project_dir)


def test_load_history_rejects_bad_entries_type(tmp_path):
    config = _make_project(tmp_path)
    path = history_path(config.project_dir)
    path.parent.mkdir(parents=True)
    path.write_text("version: 1\nentries: not-a-list\n")
    with pytest.raises(HistoryError):
        load_history(config.project_dir)


# --- build pipeline wiring (no WeasyPrint) ---------------------------------


def test_run_build_records_a_build_entry(tmp_path, monkeypatch):
    # Stub the PDF write so this exercises the history wiring without needing
    # WeasyPrint's native libraries.
    from prototyper import build as build_module

    monkeypatch.setattr(build_module, "assemble_pdf", lambda *a, **k: None)
    config = _make_project(tmp_path, data="name\nCard 0\nCard 1\n")

    plan = build_module.run_build(tmp_path)

    entries = load_history(config.project_dir)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["type"] == "build"
    assert entry["components"] == len(plan.components)
    assert entry["sheets"] == len(plan.layout.sheets)
    assert entry["inputs_hash"] == hash_inputs(config)
