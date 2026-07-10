"""Tests for PyPI packaging readiness (task: Prepare PyPI packaging and publish).

These assert the things that make the difference between "it builds" and "it
is a good citizen on PyPI": a real long description with the right content
type, a LICENSE file matching the declared license, a single source of truth
for the version, and a wheel whose metadata a user (and PyPI) will actually
see. The heavier check actually builds the wheel and inspects its METADATA;
it skips cleanly where the build backend isn't importable, matching how the
rest of the suite degrades gracefully.
"""

import pathlib
import subprocess
import sys
import zipfile

import pytest

import prototyper

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _load_pyproject():
    tomllib = pytest.importorskip("tomllib")
    return tomllib.loads(_read("pyproject.toml"))


def test_readme_is_substantial():
    # README.md is the PyPI long description; an empty one ships a blank
    # project page. It must actually describe the tool and how to install it.
    readme = _read("README.md")
    assert len(readme.strip()) > 400, "README.md is too short to be a real long description"
    assert "prototyper" in readme
    assert "pip install" in readme
    # The three user-facing commands should be documented.
    for command in ("build", "watch", "note"):
        assert command in readme


def test_license_file_present_and_mit():
    license_text = _read("LICENSE")
    assert "MIT" in license_text
    assert "Permission is hereby granted" in license_text


def test_version_is_single_sourced_from_package():
    # The version must not be duplicated as a literal in pyproject.toml, where
    # it silently drifts from prototyper.__version__. It should be declared
    # dynamic and sourced from the package.
    data = _load_pyproject()
    project = data["project"]
    assert "version" not in project, "version should be dynamic, not a hardcoded literal"
    assert "version" in project.get("dynamic", [])
    version_cfg = data["tool"]["hatch"]["version"]
    assert version_cfg["path"] == "src/prototyper/__init__.py"


def test_readme_declared_as_project_readme():
    project = _load_pyproject()["project"]
    assert project["readme"] == "README.md"


def _build_wheel(tmp_path):
    """Build a wheel from the repo into tmp_path; skip if backend is absent."""
    for module in ("build", "hatchling"):
        pytest.importorskip(module)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(tmp_path),
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"wheel build failed:\n{result.stdout}\n{result.stderr}"
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def _wheel_metadata(wheel_path):
    with zipfile.ZipFile(wheel_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        return zf.read(name).decode("utf-8")


def test_built_wheel_has_rich_metadata(tmp_path):
    wheel = _build_wheel(tmp_path)
    metadata = _wheel_metadata(wheel)

    # Long description is present and rendered as Markdown on PyPI.
    assert "Description-Content-Type: text/markdown" in metadata
    # The description body (after the metadata headers) is non-empty.
    _, _, body = metadata.partition("\n\n")
    assert "prototyper" in body

    # Version in the artifact matches the single package source of truth.
    assert f"Version: {prototyper.__version__}" in metadata

    # License is discoverable both as a classifier and (modern metadata) a file.
    assert "License :: OSI Approved :: MIT License" in metadata


def test_built_wheel_includes_console_entry_point(tmp_path):
    wheel = _build_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt"))
        entry_points = zf.read(name).decode("utf-8")
    assert "[console_scripts]" in entry_points
    assert "prototyper = prototyper.cli:main" in entry_points
