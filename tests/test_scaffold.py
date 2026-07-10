"""Tests for the package scaffold (task: Scaffold Python package structure).

These assert the minimum a real, pip-installable package must provide:
an importable package with a version, and a working console-script entry
point that responds to --version and --help.
"""

import os
import pathlib
import subprocess
import sys

import prototyper

SRC = str(pathlib.Path(__file__).resolve().parent.parent / "src")


def test_package_exposes_version():
    assert isinstance(prototyper.__version__, str)
    # A dotted, non-empty version string.
    assert prototyper.__version__
    assert "." in prototyper.__version__


def test_cli_main_is_importable():
    from prototyper.cli import main

    assert callable(main)


def test_cli_version_flag(capsys):
    from prototyper.cli import main

    # argparse's version action prints and exits via SystemExit(0).
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert prototyper.__version__ in out


def test_cli_help_lists_commands(capsys):
    from prototyper.cli import main

    # --help exits via SystemExit(0) in argparse.
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    for command in ("build", "watch", "note"):
        assert command in out


def test_console_script_module_runs():
    # `python -m prototyper --version` works end to end.
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "prototyper", "--version"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert prototyper.__version__ in result.stdout
