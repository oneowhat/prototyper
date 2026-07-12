"""Command-line entry point for prototyper.

This module wires up the top-level argument parser and the subcommands
described in the PRD (`build`, `watch`, `note`). The parser is stdlib-only
(argparse) and the heavy pipeline imports (Jinja2/WeasyPrint, pulled in by
:mod:`prototyper.build`) are deferred into each subcommand handler, so
``prototyper --version`` / ``--help`` and unrelated subcommands still work
even before the rendering dependencies are importable.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__


def _add_build(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "build",
        help="Render the project's data + template into a print-ready PDF.",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Path to the project directory or its project.yaml "
        "(default: current directory).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output PDF path (default: <project>/build/<name>.pdf).",
    )
    parser.set_defaults(func=_cmd_build)


def _add_watch(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "watch",
        help="Live-preview a component and rebuild the PDF on file changes.",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Path to the project directory or its project.yaml "
        "(default: current directory).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output PDF path for rebuilds (default: <project>/build/<name>.pdf).",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="Which component (data row) to show in the live preview "
        "(default: 0, the first).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host for the live preview server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for the live preview server (default: 8000).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Seconds between file-change checks (default: 1.0).",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Disable the live browser preview; only rebuild the PDF.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Disable PDF rebuilds; only run the live browser preview.",
    )
    parser.set_defaults(func=_cmd_watch)


def _add_note(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "note",
        help="Attach a rationale entry to the project's history log.",
    )
    parser.add_argument(
        "message",
        help="The rationale text to record "
        '(e.g. "lowered this card\'s cost from 3 to 2 for balance").',
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Path to the project directory or its project.yaml "
        "(default: current directory).",
    )
    parser.set_defaults(func=_cmd_note)


def _cmd_build(args: argparse.Namespace) -> int:
    # Imported lazily so `--version`/`--help` and other subcommands don't
    # require the rendering stack (Jinja2/WeasyPrint) to be importable.
    from .build import run_build
    from .config import ConfigError
    from .data import DataError
    from .history import HistoryError
    from .pack import PackError
    from .pdf import PdfError
    from .render import RenderError
    from .sizing import SizeError

    try:
        plan = run_build(args.project, args.output)
    except (
        ConfigError,
        DataError,
        SizeError,
        PackError,
        RenderError,
        PdfError,
        HistoryError,
    ) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Built {plan.output_path} — {len(plan.components)} component(s) "
        f"on {len(plan.layout.sheets)} sheet(s)."
    )
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    # Imported lazily so `--version`/`--help` and other subcommands don't need
    # the rendering stack (the session pulls in Jinja2/WeasyPrint on demand).
    from . import watch as watch_mod
    from .config import ConfigError

    def on_change(changed: tuple) -> None:
        names = ", ".join(sorted({p.name for p in changed})) or "input"
        print(f"Change detected ({names}); rebuilding…")

    def on_rebuild(plan) -> None:
        print(
            f"Rebuilt {plan.output_path} — {len(plan.components)} component(s) "
            f"on {len(plan.layout.sheets)} sheet(s)."
        )

    def on_error(exc: Exception) -> None:
        print(f"Rebuild failed: {exc}", file=sys.stderr)

    kwargs = {
        "index": args.index,
        "enable_preview": not args.no_preview,
        "enable_build": not args.no_build,
        "on_change": on_change,
        "on_rebuild": on_rebuild,
        "on_error": on_error,
    }
    if args.host is not None:
        kwargs["host"] = args.host
    if args.port is not None:
        kwargs["port"] = args.port
    if args.poll_interval is not None:
        kwargs["poll_interval"] = args.poll_interval

    try:
        # A bad project (ConfigError) or an unavailable preview port (OSError)
        # both fail here, before the blocking loop — report cleanly, exit 1.
        session = watch_mod.WatchSession(args.project, args.output, **kwargs)
    except (ConfigError, OSError) as exc:
        print(f"watch failed: {exc}", file=sys.stderr)
        return 1

    session.start()
    if session.preview_url is not None:
        print(f"Live preview at {session.preview_url}")
    if not args.no_build:
        print(f"Watching {session.project_dir} for changes; rebuilding on save.")
    print("Press Ctrl-C to stop.")
    try:
        session.run()
    except KeyboardInterrupt:
        print("\nStopping watch.")
    finally:
        session.stop()
        session.close()
    return 0


def _cmd_note(args: argparse.Namespace) -> int:
    # Note only touches the config loader and the history log — no rendering
    # stack — so its imports stay light and local like the other subcommands.
    from .config import ConfigError, load_project
    from .history import HistoryError, record_note

    try:
        config = load_project(args.project)
        entry = record_note(config.project_dir, args.message)
    except (ConfigError, HistoryError) as exc:
        print(f"note failed: {exc}", file=sys.stderr)
        return 1

    if entry["build"] is not None:
        print(f"Noted, attached to the build at {entry['build']}.")
    else:
        print("Noted (standalone — no build recorded yet).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prototyper",
        description="Build print-ready PDF sheets of tabletop game components.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"prototyper {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    _add_build(subparsers)
    _add_watch(subparsers)
    _add_note(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
