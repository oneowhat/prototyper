"""The ``build`` pipeline: a project folder -> a print-ready PDF.

This is where every earlier stage module meets. Given a project path it:

1. loads and validates ``project.yaml`` (:mod:`prototyper.config`);
2. loads the component CSV (:mod:`prototyper.data`);
3. resolves the component size and the layout's margin/gutter length
   strings to inches (:mod:`prototyper.sizing`);
4. packs one component per data row onto 8.5x11 sheets
   (:mod:`prototyper.pack`);
5. renders each row's HTML (:mod:`prototyper.render`);
6. computes cut lines when the layout enables them
   (:mod:`prototyper.cutlines`); and
7. writes the multi-page PDF (:mod:`prototyper.pdf`).

The pipeline is split in two, mirroring the geometry-vs-render split the
stage modules already use:

- :func:`plan_build` is the **pure** planning step — it runs stages 1-6 and
  returns a :class:`BuildPlan`. It touches no PDF library, so the bulk of
  the build is testable without WeasyPrint's native (Pango/Cairo/GObject)
  dependencies installed.
- :func:`run_build` calls :func:`plan_build` and then hands the plan to
  WeasyPrint via :func:`prototyper.pdf.assemble_pdf`, which imports the
  library lazily.

Each stage raises its own descriptive exception (``ConfigError``,
``DataError``, ``SizeError``, ``PackError``, ``RenderError``, ``PdfError``);
this module lets them propagate unchanged so the CLI can turn any of them
into a single clean "build failed: ..." message.

Automatic history logging on build (PRD "Design memory") is a separate,
later task; this module deliberately does the render-to-PDF work only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig, load_project
from .cutlines import CutLine, cut_lines_for_layout
from .data import load_data
from .pack import PackedLayout, pack_components
from .pdf import assemble_pdf
from .render import render_component
from .sizing import parse_length, resolve_size

# Where a build writes when the caller gives no explicit output path: a
# ``build/`` folder inside the project, named after the project. Keeping
# generated output in one predictable, project-local place makes it easy to
# find and easy to .gitignore.
DEFAULT_OUTPUT_SUBDIR = "build"


@dataclass(frozen=True)
class BuildPlan:
    """Everything a build produces up to (but not including) the PDF write.

    ``components`` is the rendered HTML per data row, in data order (indexed
    by :class:`~prototyper.pack.Placement.index`). ``cut_lines`` is one
    tuple of :class:`~prototyper.cutlines.CutLine` per sheet when the layout
    enables cut lines, or ``None`` when it disables them. ``output_path`` is
    where :func:`run_build` will write the PDF.
    """

    config: ProjectConfig
    layout: PackedLayout
    components: tuple[str, ...]
    cut_lines: tuple[tuple[CutLine, ...], ...] | None
    output_path: Path


def default_output_path(config: ProjectConfig) -> Path:
    """Return the default PDF path for a project: ``<dir>/build/<name>.pdf``."""
    return config.project_dir / DEFAULT_OUTPUT_SUBDIR / f"{config.name}.pdf"


def plan_build(
    project_path: str | Path,
    output_path: str | Path | None = None,
) -> BuildPlan:
    """Run every build stage short of writing the PDF and return a plan.

    ``project_path`` may be a project directory or its ``project.yaml``.
    ``output_path`` overrides the default output location. Raises the stage
    exception (``ConfigError``, ``DataError``, ``SizeError``, ``PackError``,
    ``RenderError``) of whichever step first fails.
    """
    config = load_project(project_path)
    dataset = load_data(config.data_path)

    size = resolve_size(config.component)
    margin_in = parse_length(config.layout.margin, field="margin")
    gutter_in = parse_length(config.layout.gutter, field="gutter")

    layout = pack_components(
        len(dataset), size, margin_in=margin_in, gutter_in=gutter_in
    )

    components = tuple(
        render_component(config.template_path, row) for row in dataset.rows
    )

    cut_lines = cut_lines_for_layout(layout) if config.layout.cut_lines else None

    out = Path(output_path) if output_path is not None else default_output_path(config)

    return BuildPlan(
        config=config,
        layout=layout,
        components=components,
        cut_lines=cut_lines,
        output_path=out,
    )


def run_build(
    project_path: str | Path,
    output_path: str | Path | None = None,
) -> BuildPlan:
    """Plan the build and write the PDF, returning the executed plan.

    Relative template assets (images, fonts) resolve against the project
    directory. Raises the same stage exceptions as :func:`plan_build`, plus
    :class:`~prototyper.pdf.PdfError` if the PDF can't be written (e.g.
    WeasyPrint is unavailable).
    """
    plan = plan_build(project_path, output_path)
    assemble_pdf(
        plan.layout,
        plan.components,
        plan.output_path,
        cut_lines=plan.cut_lines,
        base_url=plan.config.project_dir,
    )
    return plan
