"""Project file watcher with a PDF-rebuild trigger.

This is the PRD ``watch`` command's second feedback loop: while the preview
server (:mod:`prototyper.preview`) gives fast, single-component styling
iteration, the watcher checks the *true* final page layout by rebuilding the
whole PDF whenever a project input changes. This task builds the watcher
itself, standalone; the ``watch`` CLI command (a later task) will drive it
alongside the preview server.

The module mirrors the pipeline's pure-vs-side-effect split:

- :func:`scan_inputs` and :func:`diff_snapshots` are **pure**: the first
  walks the project tree and returns a ``{path: (mtime, size)}`` snapshot;
  the second compares two snapshots and returns the set of changed paths.
  Change detection is therefore testable with no sockets, threads, or
  rendering stack.
- :class:`ProjectWatcher` is the driver: it holds the current snapshot and,
  on each :meth:`~ProjectWatcher.poll`, rescans and fires an injectable
  ``on_change`` callback if anything moved. :meth:`~ProjectWatcher.watch`
  runs that poll on an interval until :meth:`~ProjectWatcher.stop`.

Change detection is **polling**-based (compare mtime + size on an interval)
rather than OS filesystem events, keeping the module dependency-free and
stdlib-only, consistent with the rest of the tool.

Two directories are ignored by default: the build output directory and the
``.prototyper`` history log. A rebuild *writes* both, so watching them would
make every rebuild trigger another rebuild — an infinite loop. Callers that
write output elsewhere (e.g. a ``build -o`` override) can pass extra paths
via ``ignore``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Iterable

from .config import ProjectConfig, load_project
from .history import HISTORY_SUBDIR

# How often :meth:`ProjectWatcher.watch` rescans, in seconds. A second is
# responsive enough for a hand-editing loop without busy-spinning the disk.
DEFAULT_POLL_INTERVAL = 1.0

# The (mtime, size) fingerprint of one file.
_Fingerprint = tuple[float, int]
Snapshot = dict[str, _Fingerprint]


def default_ignores(config: ProjectConfig) -> tuple[Path, ...]:
    """Directories a watch should skip because a rebuild writes into them.

    These are the ``.prototyper`` history directory and the project's default
    build output directory; watching either would turn one rebuild into an
    infinite chain of rebuilds.
    """
    # Imported lazily so merely importing this module doesn't pull in the
    # rendering stack that :mod:`prototyper.build` sits on top of.
    from .build import default_output_path

    return (
        config.project_dir / HISTORY_SUBDIR,
        default_output_path(config).parent,
    )


def scan_inputs(
    project_dir: str | Path, *, ignore: Iterable[str | Path] = ()
) -> Snapshot:
    """Return a ``{absolute_path: (mtime, size)}`` snapshot of a project tree.

    Walks ``project_dir`` recursively, skipping any directory listed in
    ``ignore`` (matched by resolved path, so nothing under an ignored
    directory is descended into). Files that vanish mid-walk are simply
    omitted rather than raising, so a snapshot never fails on a transient
    delete.
    """
    root = Path(project_dir).resolve()
    ignored = {Path(p).resolve() for p in ignore}
    snapshot: Snapshot = {}

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath).resolve()
        # Prune ignored subdirectories in place so os.walk never descends
        # into them (and their contents never reach the snapshot).
        dirnames[:] = [
            name for name in dirnames if (current / name).resolve() not in ignored
        ]
        for name in filenames:
            fpath = current / name
            try:
                st = fpath.stat()
            except OSError:
                # File disappeared between listing and stat; skip it.
                continue
            snapshot[str(fpath)] = (st.st_mtime, st.st_size)

    return snapshot


def diff_snapshots(old: Snapshot, new: Snapshot) -> set[str]:
    """Return the set of paths that were added, removed, or modified.

    A path counts as changed if it is present in exactly one snapshot, or
    present in both with a different ``(mtime, size)`` fingerprint.
    """
    changed = {key for key, value in new.items() if old.get(key) != value}
    changed.update(key for key in old if key not in new)
    return changed


class ProjectWatcher:
    """Polls a project's input files and fires ``on_change`` on any change.

    Constructing a watcher validates the project (raising
    :class:`~prototyper.config.ConfigError` if it can't be loaded) and takes
    an initial snapshot, so the first :meth:`poll` only reports changes made
    *after* construction. ``on_change`` receives a sorted tuple of the
    :class:`~pathlib.Path` objects that changed.

    The build output directory and the ``.prototyper`` history log are
    ignored by default (see :func:`default_ignores`); pass ``ignore`` to skip
    additional paths.
    """

    def __init__(
        self,
        project_path: str | Path,
        *,
        on_change: Callable[[tuple[Path, ...]], object],
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        ignore: Iterable[str | Path] | None = None,
    ) -> None:
        config = load_project(project_path)
        self._project_dir = config.project_dir
        self._on_change = on_change
        self.poll_interval = poll_interval

        ignores = list(default_ignores(config))
        if ignore:
            ignores.extend(Path(p) for p in ignore)
        self._ignore = tuple(ignores)

        self._snapshot = scan_inputs(self._project_dir, ignore=self._ignore)
        self._stop = threading.Event()

    @property
    def project_dir(self) -> Path:
        """The project directory being watched."""
        return self._project_dir

    def poll(self) -> tuple[Path, ...]:
        """Rescan once; if anything changed, fire ``on_change`` and return it.

        Returns the sorted tuple of changed paths (empty if nothing changed).
        The stored snapshot is updated either way, so each change fires
        exactly once.
        """
        new = scan_inputs(self._project_dir, ignore=self._ignore)
        changed = diff_snapshots(self._snapshot, new)
        self._snapshot = new
        if not changed:
            return ()
        paths = tuple(sorted(Path(p) for p in changed))
        self._on_change(paths)
        return paths

    def watch(self) -> None:
        """Poll every ``poll_interval`` seconds until :meth:`stop` (blocks).

        Typically run on a background thread. The wait is interruptible, so
        :meth:`stop` ends the loop promptly rather than after a full interval.
        """
        self._stop.clear()
        # Event.wait returns True once the stop event is set, False on timeout;
        # so this waits one interval between polls and exits promptly on stop.
        while not self._stop.wait(self.poll_interval):
            self.poll()

    def stop(self) -> None:
        """Signal a running :meth:`watch` loop to exit."""
        self._stop.set()


def make_rebuilder(
    project_path: str | Path,
    output_path: str | Path | None = None,
    *,
    on_error: Callable[[Exception], object] | None = None,
    on_success: Callable[[object], object] | None = None,
) -> Callable[[tuple[Path, ...]], object]:
    """Build an ``on_change`` callback that rebuilds the project's PDF.

    The returned callback ignores *which* files changed (a rebuild reruns the
    whole pipeline regardless) and calls :func:`prototyper.build.run_build`.
    A build failure (a template typo, missing data column, …) is caught and
    passed to ``on_error`` rather than propagated: a watch session must keep
    running so the designer can fix the input and re-save. On success the
    returned :class:`~prototyper.build.BuildPlan` is passed to ``on_success``.
    """
    # The pipeline errors a rebuild may raise; caught so the watch loop lives.
    from .config import ConfigError
    from .data import DataError
    from .history import HistoryError
    from .pack import PackError
    from .pdf import PdfError
    from .render import RenderError
    from .sizing import SizeError

    build_errors = (
        ConfigError,
        DataError,
        SizeError,
        PackError,
        RenderError,
        PdfError,
        HistoryError,
    )

    def _rebuild(changed: tuple[Path, ...]) -> object:
        # Imported at call time so tests can monkeypatch build.run_build and
        # so the heavy rendering stack loads only when a rebuild actually runs.
        from .build import run_build

        try:
            plan = run_build(project_path, output_path)
        except build_errors as exc:
            if on_error is not None:
                on_error(exc)
            return None
        if on_success is not None:
            on_success(plan)
        return plan

    return _rebuild


class WatchSession:
    """Drive the PRD ``watch`` command's two feedback loops as one session.

    The PRD's ``watch`` combines the tool's two fast-iteration loops:

    - the **live browser preview** of a single component
      (:class:`prototyper.preview.PreviewServer`), for quick styling; and
    - the **PDF-rebuild trigger** (:class:`ProjectWatcher` +
      :func:`make_rebuilder`), which rebuilds the whole PDF on any input
      change so the designer can check true final page layout/packing.

    An edit to the template/data/config therefore both shows up on the next
    preview refresh (the preview server re-renders every request) and kicks
    off a full PDF rebuild. Either loop can be turned off independently
    (``enable_preview`` / ``enable_build``), e.g. to run a headless rebuild
    watcher with no browser preview.

    Construction validates the project (raising
    :class:`~prototyper.config.ConfigError`) and binds the preview socket
    (raising ``OSError`` if the port is taken), so both failure modes surface
    *before* the blocking loop starts. Lifecycle:

    - :meth:`start` launches the preview server on a background thread and,
      when ``initial_build`` is set, runs one build so an up-to-date PDF
      exists immediately.
    - :meth:`run` blocks (typically the caller's main thread, so ``Ctrl-C``
      lands here) until :meth:`stop`.
    - :meth:`stop` ends the loop and the preview server; :meth:`close`
      releases the socket. The class is also a context manager that stops and
      closes on exit.

    ``on_change`` (changed paths), ``on_rebuild`` (the successful
    :class:`~prototyper.build.BuildPlan`), and ``on_error`` (a caught build
    error) are optional reporting hooks the CLI uses to print progress; a
    build failure is reported through ``on_error`` but never stops the
    session, so the designer can fix the input and re-save.
    """

    def __init__(
        self,
        project_path: str | Path,
        output_path: str | Path | None = None,
        *,
        index: int = 0,
        host: str | None = None,
        port: int | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        enable_preview: bool = True,
        enable_build: bool = True,
        initial_build: bool = True,
        on_change: Callable[[tuple[Path, ...]], object] | None = None,
        on_rebuild: Callable[[object], object] | None = None,
        on_error: Callable[[Exception], object] | None = None,
        ignore: Iterable[str | Path] | None = None,
    ) -> None:
        # Validate the project up front (fail loud before binding a socket or
        # starting any thread), and resolve the static-serving root.
        config = load_project(project_path)
        self._project_dir = config.project_dir
        self._initial_build = initial_build

        self._preview_server = None
        self._server_thread: threading.Thread | None = None
        self._watcher: ProjectWatcher | None = None
        self._rebuilder: Callable[[tuple[Path, ...]], object] | None = None
        self._done = threading.Event()

        if enable_preview:
            # Imported lazily: the preview server pulls in the render stack
            # (Jinja2), which merely importing this module should not require.
            from .preview import DEFAULT_HOST, DEFAULT_PORT, PreviewServer

            self._preview_server = PreviewServer(
                project_path,
                index=index,
                host=DEFAULT_HOST if host is None else host,
                port=DEFAULT_PORT if port is None else port,
            )

        if enable_build:
            self._rebuilder = make_rebuilder(
                project_path,
                output_path,
                on_success=on_rebuild,
                on_error=on_error,
            )

            def _on_change(changed: tuple[Path, ...]) -> object:
                if on_change is not None:
                    on_change(changed)
                assert self._rebuilder is not None
                return self._rebuilder(changed)

            self._watcher = ProjectWatcher(
                project_path,
                on_change=_on_change,
                poll_interval=poll_interval,
                ignore=ignore,
            )

    @property
    def project_dir(self) -> Path:
        """The project directory being watched / served."""
        return self._project_dir

    @property
    def preview_url(self) -> str | None:
        """The live-preview URL, or ``None`` when the preview loop is off."""
        if self._preview_server is None:
            return None
        return self._preview_server.url

    def start(self) -> None:
        """Start the preview server thread and run the initial build (if any).

        The preview server runs on a daemon thread so :meth:`run` can block
        the caller's main thread on the watch loop. When ``initial_build`` was
        set and the build loop is enabled, one build runs now so an up-to-date
        PDF exists before the first edit; a failure there is reported via
        ``on_error`` and does not stop the session.
        """
        if self._preview_server is not None:
            self._server_thread = threading.Thread(
                target=self._preview_server.serve_forever, daemon=True
            )
            self._server_thread.start()
        if self._initial_build and self._rebuilder is not None:
            # Empty tuple: no specific file changed, this is the startup build.
            self._rebuilder(())

    def run(self) -> None:
        """Block until :meth:`stop` (typically the caller's main thread).

        Runs the polling watch loop when the build loop is enabled; otherwise
        (preview-only) simply waits so the preview server keeps serving until
        stopped. Because this blocks the caller's thread, a ``KeyboardInterrupt``
        (``Ctrl-C``) propagates to the caller to end the session.
        """
        if self._watcher is not None:
            self._watcher.watch()
        else:
            self._done.wait()

    def stop(self) -> None:
        """Signal :meth:`run` to return and stop the preview server."""
        self._done.set()
        if self._watcher is not None:
            self._watcher.stop()
        if self._preview_server is not None:
            self._preview_server.shutdown()

    def close(self) -> None:
        """Release the preview socket and join the server thread."""
        if self._preview_server is not None:
            self._preview_server.server_close()
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
            self._server_thread = None

    def __enter__(self) -> "WatchSession":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
        self.close()
