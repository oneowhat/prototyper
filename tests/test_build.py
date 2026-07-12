"""Tests for the ``build`` pipeline and CLI command (task: Wire up ``build``
CLI command).

The ``build`` command is where all the previously-built stage modules meet:
it loads the project config and CSV, resolves the component size, packs the
components onto sheets, renders each one, computes cut lines, and writes the
final PDF. The pipeline is split so the *planning* (everything up to the
PDF) is testable without WeasyPrint's native libraries; only the final
:func:`prototyper.build.run_build` touches WeasyPrint, so tests that need a
real PDF skip cleanly where those libraries are absent.
"""

import textwrap

import pytest

from prototyper.build import BuildPlan, default_output_path, plan_build, run_build
from prototyper.cli import main
from prototyper.config import ConfigError


def _make_project(root, *, rows=3, cut_lines=True, layout_extra=""):
    """Write a minimal but complete project under ``root`` and return its dir."""
    (root / "data").mkdir()
    (root / "templates").mkdir()

    header = "name,cost\n"
    body = "".join(f"Card {i},{i}\n" for i in range(rows))
    (root / "data" / "cards.csv").write_text(header + body)

    (root / "templates" / "card.html").write_text(
        "<div class=\"card\"><h1>{{ name }}</h1><span>{{ cost }}</span></div>"
    )

    cut = "true" if cut_lines else "false"
    (root / "project.yaml").write_text(
        textwrap.dedent(
            f"""\
            name: my-deck
            component:
              size: poker
            data: data/cards.csv
            template: templates/card.html
            layout:
              cut_lines: {cut}
            {layout_extra}
            """
        )
    )
    return root


# --- planning (no WeasyPrint needed) ---------------------------------------


def test_plan_build_returns_a_plan(tmp_path):
    _make_project(tmp_path, rows=3)
    plan = plan_build(tmp_path)
    assert isinstance(plan, BuildPlan)
    assert len(plan.components) == 3
    assert len(plan.layout.sheets) == 1


def test_plan_build_renders_each_row(tmp_path):
    _make_project(tmp_path, rows=2)
    plan = plan_build(tmp_path)
    assert "Card 0" in plan.components[0]
    assert "Card 1" in plan.components[1]


def test_plan_build_default_output_path(tmp_path):
    _make_project(tmp_path)
    plan = plan_build(tmp_path)
    assert plan.output_path == default_output_path(plan.config)
    # Default lands under the project's build/ dir, named after the project.
    assert plan.output_path.name == "my-deck.pdf"
    assert plan.output_path.parent.name == "build"


def test_plan_build_honours_explicit_output(tmp_path):
    _make_project(tmp_path)
    out = tmp_path / "elsewhere" / "custom.pdf"
    plan = plan_build(tmp_path, out)
    assert plan.output_path == out


def test_plan_build_includes_cut_lines_when_enabled(tmp_path):
    _make_project(tmp_path, cut_lines=True)
    plan = plan_build(tmp_path)
    assert plan.cut_lines is not None
    assert len(plan.cut_lines) == len(plan.layout.sheets)


def test_plan_build_omits_cut_lines_when_disabled(tmp_path):
    _make_project(tmp_path, cut_lines=False)
    plan = plan_build(tmp_path)
    assert plan.cut_lines is None


def test_plan_build_paginates_across_sheets(tmp_path):
    # Poker cards: ~6 per 8.5x11 page with default margins, so 20 spill over.
    _make_project(tmp_path, rows=20)
    plan = plan_build(tmp_path)
    assert len(plan.layout.sheets) > 1
    placed = sum(len(s.placements) for s in plan.layout.sheets)
    assert placed == 20


def test_plan_build_propagates_config_error(tmp_path):
    with pytest.raises(ConfigError):
        plan_build(tmp_path)  # no project.yaml here


# --- CLI wiring ------------------------------------------------------------


def test_cli_build_reports_error_without_traceback(tmp_path, capsys):
    # An invalid project (no project.yaml) should exit 1 with a clean message,
    # not a traceback. This path never reaches WeasyPrint.
    code = main(["build", str(tmp_path)])
    assert code == 1
    err = capsys.readouterr().err
    assert "build failed" in err
    assert "project.yaml" in err


def test_cli_build_defaults_project_to_cwd(tmp_path, monkeypatch, capsys):
    # `build` with no path argument builds the current directory; an empty cwd
    # fails cleanly (exit 1) rather than crashing on a missing argument.
    monkeypatch.chdir(tmp_path)
    code = main(["build"])
    assert code == 1
    assert "build failed" in capsys.readouterr().err


# --- full pipeline (needs WeasyPrint) --------------------------------------


def _weasyprint_or_skip():
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:  # OSError (missing native libs) or ImportError
        pytest.skip(f"weasyprint unavailable in this environment: {exc}")


def test_run_build_writes_pdf_at_default_path(tmp_path):
    _weasyprint_or_skip()
    _make_project(tmp_path, rows=5)
    plan = run_build(tmp_path)
    assert plan.output_path.exists()
    data = plan.output_path.read_bytes()
    assert data.startswith(b"%PDF-")


def test_cli_build_success(tmp_path, capsys):
    _weasyprint_or_skip()
    _make_project(tmp_path, rows=3)
    out = tmp_path / "deck.pdf"
    code = main(["build", str(tmp_path), "--output", str(out)])
    assert code == 0
    assert out.exists()
    report = capsys.readouterr().out
    assert str(out) in report
