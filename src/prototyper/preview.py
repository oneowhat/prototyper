"""Live browser preview server for a single rendered component.

This is the PRD's "fast styling iteration" feedback loop: a small local HTTP
server that shows *one* rendered component in the browser (not the paginated
PDF), so a designer can tweak the template/CSS and just refresh. It is the
component the later ``watch`` command drives alongside the PDF-rebuild
trigger; this task builds the server itself, standalone.

The module mirrors the pipeline's pure-vs-side-effect split:

- :func:`render_preview` is **pure** (no socket): given a project path and a
  component index it loads the config and CSV, resolves the component size,
  renders that one row's HTML (:mod:`prototyper.render`), and wraps it in a
  full HTML document sized to the component's physical dimensions — the same
  trim box the PDF stage would give it. It re-reads the files on every call,
  which is what makes a browser refresh pick up edits.
- :class:`PreviewServer` is a thin :class:`~http.server.ThreadingHTTPServer`
  wrapper. Requests for ``/`` re-render the preview live; any other path is
  served as a static file from the project directory so the template's
  relative asset references (images, fonts under ``assets/``) resolve exactly
  as they do against the PDF stage's ``base_url``.

Consistent with the rest of the pipeline, the server never crashes on a
broken template mid-edit: a render failure is caught and shown as an HTML
error page in the browser so the designer can fix it and refresh.
"""

from __future__ import annotations

import html
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .config import ConfigError, load_project
from .data import DataError, load_data
from .render import RenderError, render_component
from .sizing import SizeError, resolve_size

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# The stage errors a live render can raise; the server catches these to show
# an in-browser error page rather than dropping the connection.
_RENDER_ERRORS = (ConfigError, DataError, SizeError, RenderError)


class PreviewError(Exception):
    """Raised when a component can't be previewed (e.g. index out of range)."""


def _fmt_in(value: float) -> str:
    """Format an inch measurement compactly (trimming float noise)."""
    return f"{value:g}in"


def _wrap_document(inner_html: str, *, title: str, width_in: float, height_in: float) -> str:
    """Wrap one component's HTML in a full page sized to its trim box.

    The component sits in a white, physically-sized frame on a neutral
    backdrop — the same width/height the PDF stage would give it — so the
    designer sees the true finished size while iterating on styling.
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        "<style>\n"
        "html, body { margin: 0; padding: 0; }\n"
        "body { background: #d9d9d9; display: flex; align-items: flex-start; "
        "justify-content: center; min-height: 100vh; box-sizing: border-box; "
        "padding: 2rem; }\n"
        f".preview-frame {{ width: {_fmt_in(width_in)}; height: {_fmt_in(height_in)}; "
        "background: #fff; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25); "
        "overflow: hidden; box-sizing: border-box; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f'<div class="preview-frame">{inner_html}</div>\n'
        "</body>\n"
        "</html>\n"
    )


def _error_document(message: str) -> str:
    """A minimal HTML page surfacing a render error in the browser."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Preview error</title>\n"
        "<style>\n"
        "body { font-family: system-ui, sans-serif; margin: 2rem; color: #611; }\n"
        "pre { background: #f6e9e9; padding: 1rem; border-radius: 4px; "
        "white-space: pre-wrap; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>Preview error</h1>\n"
        f"<pre>{html.escape(message)}</pre>\n"
        "<p>Fix the problem and refresh.</p>\n"
        "</body>\n"
        "</html>\n"
    )


def render_preview(project_path: str | Path, index: int = 0) -> str:
    """Render one project component as a standalone HTML preview document.

    ``project_path`` may be a project directory or its ``project.yaml``.
    ``index`` selects which data row to preview (0 = the first component).
    Returns a full HTML document sized to the component's physical trim box.

    Re-reads the config, CSV, and template on every call, so successive calls
    reflect on-disk edits. Raises :class:`PreviewError` if ``index`` is out of
    range, and propagates the underlying stage error (``ConfigError``,
    ``DataError``, ``SizeError``, ``RenderError``) if a stage fails.
    """
    config = load_project(project_path)
    dataset = load_data(config.data_path)

    if not 0 <= index < len(dataset):
        raise PreviewError(
            f"component index {index} is out of range "
            f"(project has {len(dataset)} component(s), valid indices 0.."
            f"{len(dataset) - 1})"
        )

    size = resolve_size(config.component)
    inner = render_component(config.template_path, dataset.rows[index])
    title = f"{config.name} — component {index}"
    return _wrap_document(
        inner, title=title, width_in=size.width_in, height_in=size.height_in
    )


class _PreviewHandler(SimpleHTTPRequestHandler):
    """Serve the live component preview at ``/`` and static assets elsewhere."""

    # Set per-server by :class:`PreviewServer` via a :func:`functools.partial`.
    project_path: str | Path = "."
    index: int = 0

    def _is_root(self) -> bool:
        return urlsplit(self.path).path in ("/", "/index.html", "")

    def _serve_preview(self, *, head_only: bool = False) -> None:
        try:
            body = render_preview(self.project_path, self.index).encode("utf-8")
            status = 200
        except (PreviewError, *_RENDER_ERRORS) as exc:
            body = _error_document(str(exc)).encode("utf-8")
            status = 500

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # A preview should always re-render; never let a browser cache it.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        if self._is_root():
            self._serve_preview()
        else:
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 (http.server naming)
        if self._is_root():
            self._serve_preview(head_only=True)
        else:
            super().do_HEAD()

    def log_message(self, *args) -> None:  # noqa: A002 - silence dev-server noise
        pass


class PreviewServer:
    """A local HTTP server that live-previews one project component.

    Binds immediately on construction (validating that the project loads), so
    :attr:`url`/:attr:`port` are available right away; call
    :meth:`serve_forever` (typically on a background thread) to handle
    requests. ``index`` selects which component to preview.

    Raises :class:`~prototyper.config.ConfigError` if the project can't be
    loaded, or ``OSError`` if the host/port can't be bound.
    """

    def __init__(
        self,
        project_path: str | Path,
        *,
        index: int = 0,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.project_path = project_path
        self.index = index
        # Resolve the project directory up front: it validates the project
        # (fail loud before binding a socket) and gives the static-file root
        # against which the template's relative asset paths resolve.
        config = load_project(project_path)
        self._project_dir = config.project_dir

        # A dedicated handler subclass per server carries this server's render
        # context as class attributes, so concurrent PreviewServers (e.g. two
        # projects) never clobber each other's project_path/index.
        handler_cls = type(
            "_BoundPreviewHandler",
            (_PreviewHandler,),
            {"project_path": project_path, "index": index},
        )
        handler = partial(handler_cls, directory=str(self._project_dir))
        self._httpd = ThreadingHTTPServer((host, port), handler)

    @property
    def project_dir(self) -> Path:
        """The project directory static assets are served from."""
        return self._project_dir

    @property
    def port(self) -> int:
        """The TCP port the server is bound to."""
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        """The base URL to open in a browser."""
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/"

    def serve_forever(self) -> None:
        """Handle requests until :meth:`shutdown` is called (blocks)."""
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """Stop a running :meth:`serve_forever` loop."""
        self._httpd.shutdown()

    def server_close(self) -> None:
        """Release the bound socket."""
        self._httpd.server_close()

    def __enter__(self) -> "PreviewServer":
        return self

    def __exit__(self, *exc) -> None:
        self.shutdown()
        self.server_close()
