"""Tests for the live browser preview server (task: Build live browser
preview server).

The preview server is the PRD's "fast styling iteration" feedback loop: it
serves a *single* rendered component (not a paginated PDF) over HTTP so a
designer can tweak the template/CSS and refresh the browser. The module
splits into a pure :func:`prototyper.preview.render_preview` (project ->
full HTML document for one component) and a thin :class:`PreviewServer`
around it, so the rendering logic is testable without a socket and the
server can be exercised with real HTTP requests.
"""

import textwrap
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from prototyper.preview import PreviewError, PreviewServer, render_preview
from prototyper.render import RenderError


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


@contextmanager
def _running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url):
    try:
        resp = urlopen(url, timeout=5)
        return resp.status, resp.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# --- render_preview (pure) ---------------------------------------------------


def test_render_preview_returns_full_document(tmp_path):
    _make_project(tmp_path)
    html = render_preview(tmp_path)

    assert html.lstrip().startswith("<!DOCTYPE html>")
    # The first component's rendered content is embedded.
    assert "Card 0" in html
    # The document sizes the preview to the component's physical dimensions
    # (poker = 2.5 x 3.5in), mirroring how the PDF stage boxes a component.
    assert "2.5in" in html
    assert "3.5in" in html


def test_render_preview_selects_component_by_index(tmp_path):
    _make_project(tmp_path, rows=3)
    assert "Card 0" in render_preview(tmp_path)  # default
    assert "Card 0" in render_preview(tmp_path, index=0)
    two = render_preview(tmp_path, index=2)
    assert "Card 2" in two
    assert "Card 0" not in two


def test_render_preview_index_out_of_range(tmp_path):
    _make_project(tmp_path, rows=2)
    with pytest.raises(PreviewError) as exc:
        render_preview(tmp_path, index=5)
    assert "5" in str(exc.value)


def test_render_preview_reflects_edits(tmp_path):
    _make_project(tmp_path)
    assert "Card 0" in render_preview(tmp_path)

    # Re-rendering re-reads the template from disk, so an edit shows up on the
    # next call (the basis of the browser-refresh live loop).
    (tmp_path / "templates" / "card.html").write_text("<p>edited {{ name }}</p>")
    updated = render_preview(tmp_path)
    assert "edited Card 0" in updated


def test_render_preview_propagates_template_error(tmp_path):
    _make_project(tmp_path, template="<div>{{ nope }}</div>")
    with pytest.raises(RenderError):
        render_preview(tmp_path)


# --- PreviewServer (HTTP) ----------------------------------------------------


def test_server_serves_rendered_component(tmp_path):
    _make_project(tmp_path)
    server = PreviewServer(tmp_path, host="127.0.0.1", port=0)
    with _running(server):
        status, body = _get(server.url)
    assert status == 200
    assert "Card 0" in body


def test_server_url_and_port(tmp_path):
    _make_project(tmp_path)
    server = PreviewServer(tmp_path, host="127.0.0.1", port=0)
    try:
        assert server.port > 0
        assert server.url == f"http://127.0.0.1:{server.port}/"
    finally:
        server.server_close()


def test_server_serves_static_asset(tmp_path):
    _make_project(tmp_path)
    (tmp_path / "assets" / "note.txt").write_text("hello asset")
    server = PreviewServer(tmp_path, host="127.0.0.1", port=0)
    with _running(server):
        status, body = _get(server.url + "assets/note.txt")
    assert status == 200
    assert "hello asset" in body


def test_server_shows_error_page_for_broken_template(tmp_path):
    _make_project(tmp_path, template="<div>{{ missing }}</div>")
    server = PreviewServer(tmp_path, host="127.0.0.1", port=0)
    with _running(server):
        status, body = _get(server.url)
    # A broken template mid-edit shows the error in the browser instead of
    # crashing the server, so the designer can fix and refresh.
    assert status == 500
    assert "missing" in body


def test_server_reflects_edits_across_requests(tmp_path):
    _make_project(tmp_path)
    server = PreviewServer(tmp_path, host="127.0.0.1", port=0)
    with _running(server):
        _, first = _get(server.url)
        assert "Card 0" in first
        (tmp_path / "templates" / "card.html").write_text("<p>live {{ name }}</p>")
        _, second = _get(server.url)
    assert "live Card 0" in second


def test_server_bad_project_raises_on_construction(tmp_path):
    # No project.yaml: constructing the server validates the project up front.
    from prototyper.config import ConfigError

    with pytest.raises(ConfigError):
        PreviewServer(tmp_path, host="127.0.0.1", port=0)
