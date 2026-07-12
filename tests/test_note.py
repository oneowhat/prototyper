"""Tests for the manual ``note`` command (task: Implement ``note`` CLI command).

The PRD's "Design memory" pairs the automatic build entry with a manual
``note "<message>"`` command: it attaches designer-written rationale to the
history log, associated with the most recent build (or standalone if no build
has happened yet). This is the part plain diffs/commit messages don't capture
well for a non-technical audience, so getting the association right matters.

These tests exercise :func:`prototyper.history.record_note` directly and the
``note`` CLI wiring; neither path needs WeasyPrint.
"""

import textwrap

import pytest

from prototyper.cli import main
from prototyper.config import load_project
from prototyper.history import (
    HistoryError,
    load_history,
    record_build,
    record_note,
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


# --- record_note (direct) --------------------------------------------------


def test_record_note_creates_standalone_when_no_build(tmp_path):
    config = _make_project(tmp_path)
    entry = record_note(config.project_dir, "first thoughts")

    entries = load_history(config.project_dir)
    assert len(entries) == 1
    assert entries[0] is not entry  # entry is a copy written to disk
    assert entry["type"] == "note"
    assert entry["message"] == "first thoughts"
    assert entry["build"] is None
    assert entry["timestamp"]


def test_record_note_attaches_to_most_recent_build(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T00:00:00+00:00")
    entry = record_note(config.project_dir, "lowered cost 3 -> 2")

    assert entry["build"] == "2026-07-10T00:00:00+00:00"


def test_record_note_attaches_to_latest_of_several_builds(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T00:00:00+00:00")
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T05:00:00+00:00")
    entry = record_note(config.project_dir, "note after second build")

    assert entry["build"] == "2026-07-10T05:00:00+00:00"


def test_record_note_appends_after_existing_entries(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T00:00:00+00:00")
    record_note(config.project_dir, "note one",
                timestamp="2026-07-10T01:00:00+00:00")
    record_note(config.project_dir, "note two",
                timestamp="2026-07-10T02:00:00+00:00")

    entries = load_history(config.project_dir)
    assert [e["type"] for e in entries] == ["build", "note", "note"]
    assert [e.get("message") for e in entries] == [None, "note one", "note two"]


def test_record_note_uses_explicit_timestamp(tmp_path):
    config = _make_project(tmp_path)
    entry = record_note(config.project_dir, "hi",
                        timestamp="2026-07-10T09:00:00+00:00")
    assert entry["timestamp"] == "2026-07-10T09:00:00+00:00"


def test_record_note_rejects_empty_message(tmp_path):
    config = _make_project(tmp_path)
    with pytest.raises(HistoryError):
        record_note(config.project_dir, "")


def test_record_note_rejects_whitespace_only_message(tmp_path):
    config = _make_project(tmp_path)
    with pytest.raises(HistoryError):
        record_note(config.project_dir, "   \n  ")


def test_note_is_human_readable_yaml(tmp_path):
    config = _make_project(tmp_path)
    record_note(config.project_dir, "readable rationale",
                timestamp="2026-07-10T00:00:00+00:00")
    from prototyper.history import history_path

    text = history_path(config.project_dir).read_text()
    assert "type: note" in text
    assert "message: readable rationale" in text
    # Keys read in a logical (declared) order, not alphabetised.
    assert text.index("type:") < text.index("timestamp:") < text.index("message:")


def test_record_note_rejects_malformed_log(tmp_path):
    config = _make_project(tmp_path)
    from prototyper.history import history_path

    path = history_path(config.project_dir)
    path.parent.mkdir(parents=True)
    path.write_text("- just a list\n")
    with pytest.raises(HistoryError):
        record_note(config.project_dir, "hi")


# --- CLI wiring ------------------------------------------------------------


def test_cli_note_standalone_success(tmp_path, capsys):
    _make_project(tmp_path)
    code = main(["note", "initial idea", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "note" in out.lower()

    entries = load_history(tmp_path)
    assert len(entries) == 1
    assert entries[0]["type"] == "note"
    assert entries[0]["message"] == "initial idea"
    assert entries[0]["build"] is None


def test_cli_note_attaches_to_recent_build(tmp_path):
    config = _make_project(tmp_path)
    record_build(config, config.project_dir / "out.pdf", components=1, sheets=1,
                 timestamp="2026-07-10T00:00:00+00:00")
    code = main(["note", "balance tweak", str(tmp_path)])
    assert code == 0

    entries = load_history(tmp_path)
    assert entries[-1]["type"] == "note"
    assert entries[-1]["build"] == "2026-07-10T00:00:00+00:00"


def test_cli_note_defaults_project_to_cwd(tmp_path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main(["note", "from cwd"])
    assert code == 0
    entries = load_history(tmp_path)
    assert entries[-1]["message"] == "from cwd"


def test_cli_note_reports_error_without_traceback(tmp_path, capsys):
    # No project.yaml here: should exit 1 with a clean message, not a traceback.
    code = main(["note", "orphan note", str(tmp_path)])
    assert code == 1
    err = capsys.readouterr().err
    assert "note failed" in err
    assert "project.yaml" in err


def test_cli_note_requires_a_message(tmp_path):
    # argparse should reject a missing message (SystemExit, not a crash).
    with pytest.raises(SystemExit):
        main(["note"])
