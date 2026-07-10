"""Tests for the project file watcher (task: Add file watcher with PDF
rebuild trigger).

The watcher is the PRD's "PDF rebuild trigger" feedback loop: it observes a
project's input files and, on any change, fires a callback (in normal use, a
full PDF rebuild). The module splits into pure snapshot/diff helpers
(:func:`prototyper.watch.scan_inputs` / :func:`diff_snapshots`) and a
:class:`ProjectWatcher` driver, so change detection is testable without the
rendering stack and the rebuild action is injectable (so these tests never
touch WeasyPrint).
"""

import os
import textwrap
import threading
import time

import pytest

from prototyper.watch import (
    ProjectWatcher,
    diff_snapshots,
    make_rebuilder,
    scan_inputs,
)


def _make_project(root, *, rows=3, template=None, size="poker"):
    """Write a minimal but complete project under ``root`` and return its dir."""
    (root / "data").mkdir()
    (root / "templates").mkdir()
    (root / "assets").mkdir()

    header = "name,cost\n"
    body = "".join(f"Card {i},{i}\n" for i in range(rows))
    (root / "data" / "cards.csv").write_text(header + body)

    if template is None:
        template = '<div class="card"><h1>{{ name }}</h1><span>{{ cost }}</span></div>'
    (root / "templates" / "card.html").write_text(template)

    (root / "project.yaml").write_text(
        textwrap.dedent(
            f"""\
            name: my-deck
            component:
              size: {size}
            data: data/cards.csv
            template: templates/card.html
            """
        )
    )
    return root


def _edit(path, text):
    """Write ``text`` and force a strictly newer mtime.

    Guarantees the change is detectable even on filesystems whose mtime
    granularity is too coarse to distinguish two writes in the same second.
    """
    path.write_text(text)
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))


# --- scan_inputs / diff_snapshots (pure) -------------------------------------


def test_scan_inputs_includes_project_files(tmp_path):
    _make_project(tmp_path)
    snap = scan_inputs(tmp_path)

    keys = set(snap)
    assert str((tmp_path / "project.yaml").resolve()) in keys
    assert str((tmp_path / "data" / "cards.csv").resolve()) in keys
    assert str((tmp_path / "templates" / "card.html").resolve()) in keys
    # Each entry is an (mtime, size) pair.
    for value in snap.values():
        assert len(value) == 2


def test_scan_inputs_excludes_ignored_dirs(tmp_path):
    _make_project(tmp_path)
    ignore_dir = tmp_path / "build"
    ignore_dir.mkdir()
    (ignore_dir / "my-deck.pdf").write_bytes(b"%PDF-fake")

    snap = scan_inputs(tmp_path, ignore=[ignore_dir])
    assert str((ignore_dir / "my-deck.pdf").resolve()) not in snap
    # Real inputs are still present.
    assert str((tmp_path / "project.yaml").resolve()) in snap


def test_diff_snapshots_reports_added_removed_and_modified(tmp_path):
    a = {"x": (1.0, 10), "y": (2.0, 20)}
    # y modified, z added, x removed.
    b = {"y": (2.0, 21), "z": (3.0, 30)}
    changed = diff_snapshots(a, b)
    assert changed == {"x", "y", "z"}


def test_diff_snapshots_identical_is_empty():
    a = {"x": (1.0, 10)}
    assert diff_snapshots(a, dict(a)) == set()


# --- ProjectWatcher (driver) -------------------------------------------------


def test_watcher_no_change_no_trigger(tmp_path):
    _make_project(tmp_path)
    calls = []
    watcher = ProjectWatcher(tmp_path, on_change=calls.append)
    assert watcher.poll() == ()
    assert calls == []


def test_watcher_detects_template_edit(tmp_path):
    _make_project(tmp_path)
    calls = []
    watcher = ProjectWatcher(tmp_path, on_change=calls.append)

    _edit(tmp_path / "templates" / "card.html", "<p>edited {{ name }}</p>")
    changed = watcher.poll()

    assert len(calls) == 1
    changed_paths = {p.name for p in changed}
    assert "card.html" in changed_paths
    # A second poll with no further edits does not re-trigger.
    assert watcher.poll() == ()
    assert len(calls) == 1


def test_watcher_detects_new_and_deleted_files(tmp_path):
    _make_project(tmp_path)
    calls = []
    watcher = ProjectWatcher(tmp_path, on_change=calls.append)

    # A newly added asset is a change.
    (tmp_path / "assets" / "logo.png").write_bytes(b"img")
    added = watcher.poll()
    assert any(p.name == "logo.png" for p in added)

    # Deleting a watched file is also a change.
    (tmp_path / "assets" / "logo.png").unlink()
    removed = watcher.poll()
    assert any(p.name == "logo.png" for p in removed)
    assert len(calls) == 2


def test_watcher_ignores_output_and_history_writes(tmp_path):
    """A rebuild writes the PDF and the history log; those writes must not
    themselves trigger another rebuild (no infinite loop)."""
    _make_project(tmp_path)
    calls = []
    watcher = ProjectWatcher(tmp_path, on_change=calls.append)

    # Simulate what run_build writes: the default build output and history.
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "my-deck.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / ".prototyper").mkdir()
    (tmp_path / ".prototyper" / "history.yaml").write_text("version: 1\n")

    assert watcher.poll() == ()
    assert calls == []


def test_watcher_extra_ignore(tmp_path):
    _make_project(tmp_path)
    out = tmp_path / "dist"
    calls = []
    watcher = ProjectWatcher(tmp_path, on_change=calls.append, ignore=[out])

    out.mkdir()
    (out / "deck.pdf").write_bytes(b"%PDF")
    assert watcher.poll() == ()
    assert calls == []


def test_watcher_bad_project_raises_on_construction(tmp_path):
    from prototyper.config import ConfigError

    with pytest.raises(ConfigError):
        ProjectWatcher(tmp_path, on_change=lambda changed: None)


def test_watch_loop_triggers_then_stops(tmp_path):
    _make_project(tmp_path)
    event = threading.Event()

    def on_change(changed):
        event.set()

    watcher = ProjectWatcher(tmp_path, on_change=on_change, poll_interval=0.02)
    thread = threading.Thread(target=watcher.watch, daemon=True)
    thread.start()
    try:
        time.sleep(0.05)
        _edit(tmp_path / "templates" / "card.html", "<p>x {{ name }}</p>")
        assert event.wait(timeout=5), "watch loop did not fire on a file change"
    finally:
        watcher.stop()
        thread.join(timeout=5)
    assert not thread.is_alive()


# --- make_rebuilder (build integration, stubbed) -----------------------------


def test_make_rebuilder_invokes_build(tmp_path, monkeypatch):
    _make_project(tmp_path)
    seen = {}

    def fake_run_build(project_path, output_path=None):
        seen["project"] = project_path
        seen["output"] = output_path
        return "PLAN"

    import prototyper.build as build_mod

    monkeypatch.setattr(build_mod, "run_build", fake_run_build)

    successes = []
    rebuild = make_rebuilder(
        tmp_path, output_path="out.pdf", on_success=lambda plan: successes.append(plan)
    )
    result = rebuild((tmp_path / "templates" / "card.html",))

    assert result == "PLAN"
    assert seen == {"project": tmp_path, "output": "out.pdf"}
    assert successes == ["PLAN"]


def test_make_rebuilder_survives_build_error(tmp_path, monkeypatch):
    _make_project(tmp_path)
    from prototyper.render import RenderError

    def boom(project_path, output_path=None):
        raise RenderError("bad template")

    import prototyper.build as build_mod

    monkeypatch.setattr(build_mod, "run_build", boom)

    errors = []
    rebuild = make_rebuilder(tmp_path, on_error=errors.append)
    # A broken input must not propagate out of the rebuild callback: a watch
    # session has to keep running so the designer can fix and re-save.
    result = rebuild((tmp_path / "templates" / "card.html",))

    assert result is None
    assert len(errors) == 1
    assert isinstance(errors[0], RenderError)
