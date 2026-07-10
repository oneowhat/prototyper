"""Tests for the ``watch`` command wiring (task: Wire up ``watch`` CLI command).

The PRD's ``watch`` combines the tool's two fast-feedback loops into one
command: the live browser preview of a single component
(:class:`prototyper.preview.PreviewServer`) and the PDF-rebuild trigger
(:class:`prototyper.watch.ProjectWatcher`), so an edit both refreshes the
preview and rebuilds the full PDF to check true page layout.

The orchestration lives in :class:`prototyper.watch.WatchSession`, which the
``watch`` CLI command drives. These tests exercise the session directly and
the CLI wiring; the rebuild path is stubbed so none of them touch WeasyPrint.
"""

import textwrap
import threading
import time
import urllib.request

import pytest

from prototyper.cli import main


def _make_project(root, *, rows=2, template=None, size="poker"):
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
    """Write ``text`` and force a strictly newer mtime (coarse-mtime safe)."""
    import os

    path.write_text(text)
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))


# --- WatchSession (orchestration) --------------------------------------------


def test_watch_session_bad_project_raises_on_construction(tmp_path):
    from prototyper.config import ConfigError
    from prototyper.watch import WatchSession

    # No project.yaml here: constructing a session must fail loud (before any
    # socket is bound or thread is started), not after entering the loop.
    with pytest.raises(ConfigError):
        WatchSession(tmp_path)


def test_watch_session_preview_serves_a_component(tmp_path):
    from prototyper.watch import WatchSession

    _make_project(tmp_path)
    # Preview only (no build => no WeasyPrint); port 0 for an ephemeral port.
    with WatchSession(tmp_path, enable_build=False, port=0) as session:
        session.start()
        assert session.preview_url is not None
        with urllib.request.urlopen(session.preview_url, timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
    assert "Card 0" in body


def test_watch_session_no_preview_has_no_url(tmp_path):
    from prototyper.watch import WatchSession

    _make_project(tmp_path)
    with WatchSession(
        tmp_path, enable_preview=False, initial_build=False
    ) as session:
        assert session.preview_url is None


def test_watch_session_initial_build_runs_once(tmp_path, monkeypatch):
    from prototyper.watch import WatchSession
    import prototyper.build as build_mod

    _make_project(tmp_path)
    calls = []
    monkeypatch.setattr(
        build_mod, "run_build", lambda p, o=None: calls.append((p, o)) or "PLAN"
    )

    with WatchSession(tmp_path, enable_preview=False, initial_build=True):
        pass
    # start() has not been called yet, so no build has happened.
    assert calls == []


def test_watch_session_initial_build_on_start(tmp_path, monkeypatch):
    from prototyper.watch import WatchSession
    import prototyper.build as build_mod

    _make_project(tmp_path)
    calls = []
    monkeypatch.setattr(
        build_mod, "run_build", lambda p, o=None: calls.append((p, o)) or "PLAN"
    )

    rebuilds = []
    session = WatchSession(
        tmp_path,
        enable_preview=False,
        initial_build=True,
        on_rebuild=rebuilds.append,
    )
    try:
        session.start()
    finally:
        session.stop()
        session.close()

    assert len(calls) == 1
    assert rebuilds == ["PLAN"]


def test_watch_session_rebuilds_on_change(tmp_path, monkeypatch):
    from prototyper.watch import WatchSession
    import prototyper.build as build_mod

    _make_project(tmp_path)
    built = threading.Event()
    calls = []

    def fake_run_build(project_path, output_path=None):
        calls.append(project_path)
        built.set()
        return "PLAN"

    monkeypatch.setattr(build_mod, "run_build", fake_run_build)

    changed_reports = []
    session = WatchSession(
        tmp_path,
        enable_preview=False,
        initial_build=False,
        poll_interval=0.02,
        on_change=changed_reports.append,
    )
    thread = threading.Thread(target=session.run, daemon=True)
    session.start()
    thread.start()
    try:
        time.sleep(0.05)
        _edit(tmp_path / "templates" / "card.html", "<p>edited {{ name }}</p>")
        assert built.wait(timeout=5), "watch did not rebuild on a file change"
    finally:
        session.stop()
        session.close()
        thread.join(timeout=5)

    assert calls, "run_build was never called"
    assert not thread.is_alive()
    assert changed_reports, "on_change was not reported"


def test_watch_session_survives_build_error(tmp_path, monkeypatch):
    from prototyper.watch import WatchSession
    from prototyper.render import RenderError
    import prototyper.build as build_mod

    _make_project(tmp_path)
    monkeypatch.setattr(
        build_mod,
        "run_build",
        lambda p, o=None: (_ for _ in ()).throw(RenderError("boom")),
    )

    errors = []
    session = WatchSession(
        tmp_path,
        enable_preview=False,
        initial_build=True,
        on_error=errors.append,
    )
    try:
        session.start()  # initial build fails but must not raise
    finally:
        session.stop()
        session.close()

    assert len(errors) == 1
    assert isinstance(errors[0], RenderError)


# --- CLI wiring --------------------------------------------------------------


def test_cli_watch_reports_bad_project(tmp_path, capsys):
    # No project.yaml: exit 1 with a clean message, not a traceback.
    code = main(["watch", str(tmp_path)])
    assert code == 1
    err = capsys.readouterr().err
    assert "watch failed" in err
    assert "project.yaml" in err


class _FakeSession:
    """Stand-in for WatchSession that records lifecycle calls and never blocks."""

    instances = []

    def __init__(self, project_path, output_path=None, **kwargs):
        self.project_path = project_path
        self.output_path = output_path
        self.kwargs = kwargs
        self.events = []
        self.project_dir = project_path
        self.preview_url = "http://127.0.0.1:12345/"
        _FakeSession.instances.append(self)

    def start(self):
        self.events.append("start")

    def run(self):
        self.events.append("run")
        raise KeyboardInterrupt  # simulate the user pressing Ctrl-C

    def stop(self):
        self.events.append("stop")

    def close(self):
        self.events.append("close")


def test_cli_watch_runs_and_stops_cleanly(tmp_path, monkeypatch, capsys):
    _make_project(tmp_path)
    _FakeSession.instances = []
    import prototyper.watch as watch_mod

    monkeypatch.setattr(watch_mod, "WatchSession", _FakeSession)

    code = main(["watch", str(tmp_path)])
    assert code == 0

    assert len(_FakeSession.instances) == 1
    session = _FakeSession.instances[0]
    # Lifecycle: started, ran (interrupted), then stopped and closed.
    assert session.events == ["start", "run", "stop", "close"]

    out = capsys.readouterr().out
    assert session.preview_url in out
    assert "Ctrl-C" in out


def test_cli_watch_passes_flags_through(tmp_path, monkeypatch):
    _make_project(tmp_path)
    _FakeSession.instances = []
    import prototyper.watch as watch_mod

    monkeypatch.setattr(watch_mod, "WatchSession", _FakeSession)

    code = main(
        [
            "watch",
            str(tmp_path),
            "-o",
            "dist/deck.pdf",
            "--index",
            "1",
            "--no-preview",
            "--port",
            "9001",
        ]
    )
    assert code == 0

    session = _FakeSession.instances[0]
    assert str(session.project_path) == str(tmp_path)
    assert session.output_path == "dist/deck.pdf"
    assert session.kwargs["index"] == 1
    assert session.kwargs["enable_preview"] is False
    assert session.kwargs["enable_build"] is True
    assert session.kwargs["port"] == 9001


def test_cli_watch_defaults_project_to_cwd(tmp_path, monkeypatch):
    _make_project(tmp_path)
    _FakeSession.instances = []
    import prototyper.watch as watch_mod

    monkeypatch.setattr(watch_mod, "WatchSession", _FakeSession)
    monkeypatch.chdir(tmp_path)

    code = main(["watch"])
    assert code == 0
    assert _FakeSession.instances[0].project_path == "."
