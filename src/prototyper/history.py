"""Design-memory history log: the project-managed ``.prototyper/history.yaml``.

The PRD's "Design memory" goal is that a designer can open an old project — or
hand it to someone else — and understand not just *what* the current design is
but how it got there and why, without archaeology through git. The vehicle is a
single tool-managed log, one per project, at ``.prototyper/history.yaml``.

This module owns that file and the **automatic** build entry the PRD asks every
``build`` run to append: a timestamp, a content hash of the template/data/config
inputs, and the output PDF path (plus the cheap-to-capture component/sheet
counts). The **manual** ``note`` entry is a separate later task, so the on-disk
format is deliberately kept open to more entry kinds: a top-level mapping with a
``version`` and a flat, ordered ``entries`` list, each entry a mapping tagged by
``type`` (``"build"`` today, ``"note"`` later). Ordering *is* the history, so
entries are only ever appended.

Design choices mirror the rest of the pipeline:

- YAML, key order preserved (not alphabetised), so the file reads as a
  human changelog while staying machine-readable for a future AI-assisted
  feature to consume.
- Content hashing is a per-file digest of each input combined under a role
  label, so a change to *any* input (or a data/template swap) moves the hash
  and two different inputs can't collide by concatenation.
- Fail loud on a corrupt log (same stance as the config/data loaders): a
  malformed ``history.yaml`` raises :class:`HistoryError` rather than being
  silently overwritten and losing prior history.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import CONFIG_FILENAME, ProjectConfig

HISTORY_SUBDIR = ".prototyper"
HISTORY_FILENAME = "history.yaml"

# Bumped only if the on-disk schema changes incompatibly; recorded in the file
# so a future reader (or the planned AI feature) can adapt to older logs.
HISTORY_VERSION = 1


class HistoryError(Exception):
    """Raised when the history log is unreadable, malformed, or an input
    it must hash cannot be read."""


def history_path(project_dir: str | Path) -> Path:
    """Return the ``.prototyper/history.yaml`` path for a project directory."""
    return Path(project_dir) / HISTORY_SUBDIR / HISTORY_FILENAME


def hash_inputs(config: ProjectConfig) -> str:
    """Return a stable content hash of a project's build inputs.

    Hashes the three files that determine a build's output — the project
    config, the data CSV, and the template — so any edit to any of them (or a
    swap to a different data/template file) changes the hash. Each file is
    digested independently under a role label and the labelled digests are
    combined, so distinct inputs can't collide via concatenation. Returns a
    ``"sha256:<hex>"`` string. Raises :class:`HistoryError` if any input can't
    be read.
    """
    combined = hashlib.sha256()
    inputs = (
        ("config", config.project_dir / CONFIG_FILENAME),
        ("data", config.data_path),
        ("template", config.template_path),
    )
    for label, path in inputs:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise HistoryError(f"cannot read {label} input {path}: {exc}") from exc
        combined.update(label.encode("utf-8"))
        combined.update(b"\0")
        combined.update(hashlib.sha256(content).digest())
        combined.update(b"\0")
    return "sha256:" + combined.hexdigest()


def _relative_output(project_dir: Path, output_path: Path) -> str:
    """Store the output path relative to the project when it lives inside it
    (portable, reads cleanly), else as an absolute path."""
    output_path = output_path.resolve()
    try:
        return output_path.relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return str(output_path)


def _read_log(path: Path) -> dict:
    """Read the raw log mapping, returning a fresh empty one if absent."""
    if not path.is_file():
        return {"version": HISTORY_VERSION, "entries": []}
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise HistoryError(f"could not parse history log {path}: {exc}") from exc
    if raw is None:
        return {"version": HISTORY_VERSION, "entries": []}
    if not isinstance(raw, dict):
        raise HistoryError(f"history log {path} must contain a top-level mapping")
    entries = raw.get("entries", [])
    if not isinstance(entries, list):
        raise HistoryError(f"history log {path}: 'entries' must be a list")
    raw.setdefault("version", HISTORY_VERSION)
    raw["entries"] = entries
    return raw


def _write_log(path: Path, log: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(log, sort_keys=False, allow_unicode=True, default_flow_style=False)
    )


def append_entry(project_dir: str | Path, entry: dict) -> None:
    """Append one entry to the project's history log (read-modify-write).

    Creates ``.prototyper/history.yaml`` on first use. Raises
    :class:`HistoryError` if the existing log is malformed.
    """
    path = history_path(project_dir)
    log = _read_log(path)
    log["entries"].append(entry)
    _write_log(path, log)


def load_history(project_dir: str | Path) -> tuple[dict, ...]:
    """Return the project's history entries in order (empty if no log yet).

    Raises :class:`HistoryError` if the log exists but is malformed.
    """
    return tuple(_read_log(history_path(project_dir))["entries"])


def record_build(
    config: ProjectConfig,
    output_path: str | Path,
    *,
    components: int,
    sheets: int,
    timestamp: str | None = None,
) -> dict:
    """Append an automatic build entry and return it.

    Captures the PRD-required timestamp, input content hash, and output path,
    plus the (cheap) component and sheet counts. ``timestamp`` defaults to the
    current UTC time in ISO-8601 (overridable, mainly for tests). The returned
    dict is the entry as written.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entry = {
        "type": "build",
        "timestamp": timestamp,
        "inputs_hash": hash_inputs(config),
        "output": _relative_output(config.project_dir, Path(output_path)),
        "components": components,
        "sheets": sheets,
    }
    append_entry(config.project_dir, entry)
    return entry
