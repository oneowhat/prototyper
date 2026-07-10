"""Command-line entry point for prototyper.

This module wires up the top-level argument parser and the subcommands
described in the PRD (`build`, `watch`, `note`). At the scaffold stage the
subcommands are registered but not yet implemented — each raises
``NotImplementedError`` so later tasks can fill them in against a stable
CLI surface. Keeping this stdlib-only (argparse) means the package
imports and the CLI runs without pulling in rendering dependencies.
"""

from __future__ import annotations

import argparse
from typing import Sequence

from . import __version__


def _add_build(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "build",
        help="Render the project's data + template into a print-ready PDF.",
    )
    parser.set_defaults(func=_cmd_build)


def _add_watch(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "watch",
        help="Live-preview a component and rebuild the PDF on file changes.",
    )
    parser.set_defaults(func=_cmd_watch)


def _add_note(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "note",
        help="Attach a rationale entry to the project's history log.",
    )
    parser.set_defaults(func=_cmd_note)


def _cmd_build(args: argparse.Namespace) -> int:
    raise NotImplementedError("build is not implemented yet")


def _cmd_watch(args: argparse.Namespace) -> int:
    raise NotImplementedError("watch is not implemented yet")


def _cmd_note(args: argparse.Namespace) -> int:
    raise NotImplementedError("note is not implemented yet")


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
