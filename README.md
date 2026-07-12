# prototyper

**Build print-ready PDF sheets of tabletop game components from HTML/CSS
templates and CSV data.**

`prototyper` is a command-line tool for indie and hobbyist tabletop game
designers. You design one card, board, or token *once* as an HTML/CSS
template, feed it a CSV where each row is one component, and get back a
paginated, print-ready 8.5×11 PDF with the components auto-packed into a grid
and thin cut lines for home trimming.

It's a simpler, standards-based alternative to bespoke card-scripting tools:
design with the HTML and CSS you already know instead of learning a custom
scripting language.

## Features

- **HTML/CSS templates** rendered with [Jinja2](https://jinja.palletsprojects.com/) —
  each CSV column becomes a `{{ placeholder }}`.
- **Standard size presets** (poker, bridge, tarot, mini, hex-token,
  square-token) or fully custom `width`/`height`.
- **Auto-grid page packing** onto 8.5×11 sheets, with configurable margins,
  gutters, and cut lines for home trimming.
- **Fast iteration loop**: a live browser preview of a single component plus a
  watch mode that rebuilds the full PDF whenever you save.
- **Design memory**: every build and every rationale `note` is recorded to a
  human-readable `.prototyper/history.yaml`, so you (or a collaborator) can
  later understand not just *what* the design is but *how and why* it evolved.

## Installation

```sh
pip install prototyper
```

Or, to keep it isolated as a standalone CLI tool:

```sh
pipx install prototyper
```

`prototyper` renders PDFs with [WeasyPrint](https://weasyprint.org/), which
depends on native libraries (Pango, Cairo, GObject). If a build fails on
import, see WeasyPrint's
[platform installation notes](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

### macOS (Homebrew)

```sh
brew install pango gdk-pixbuf libffi
```

Homebrew installs these under `/opt/homebrew/lib`, but macOS's dynamic
linker doesn't search there by default — `pip install` will succeed, but
every `prototyper build` fails with a `dlopen`/`libgobject-2.0-0` error
until the linker is told where to look:

```sh
export DYLD_LIBRARY_PATH=/opt/homebrew/lib
```

Add that line to your shell profile (`~/.zshrc` etc.) so it's set in every
session, not just the one where you happened to export it.

## Quick start

A project is a folder tied together by a `project.yaml`:

```
my-game/
  project.yaml          # component size, data path, template path, layout
  data/
    cards.csv           # one row per component instance
  templates/
    card.html           # HTML/CSS template with {{ placeholders }}
  assets/               # optional: images and fonts referenced by the template
```

A minimal `project.yaml`:

```yaml
name: my-game
component:
  size: poker           # or set explicit width/height, e.g. width: 2.5in
data: data/cards.csv
template: templates/card.html
layout:
  margin: 0.5in
  gutter: 0.1in
  cut_lines: true
```

Build the print-ready PDF:

```sh
prototyper build my-game
# -> my-game/build/my-game.pdf
```

A complete, copy-me example lives in
[`examples/starter-cards`](examples/starter-cards) in the source repository.

## Commands

| Command | What it does |
| --- | --- |
| `prototyper build [project]` | Render the data + template into a paginated, print-ready PDF (and log an automatic build entry to the history). `-o/--output` overrides the PDF path. |
| `prototyper watch [project]` | Live browser preview of one component **and** an automatic PDF rebuild on every file change. `--no-preview` / `--no-build` run just one loop; `--host`/`--port`/`--index`/`--poll-interval` tune the preview. |
| `prototyper note "<message>" [project]` | Attach a free-text rationale entry (e.g. "lowered this card's cost from 3 to 2 for balance") to the history, associated with the most recent build. |

`[project]` defaults to the current directory and accepts either the project
folder or its `project.yaml` directly.

## Requirements

- Python 3.10+
- The runtime dependencies (`jinja2`, `weasyprint`, `pyyaml`) install
  automatically with the package.

## Development

```sh
git clone https://github.com/prototyper/prototyper
cd prototyper
pip install -e ".[dev]"
pytest
```

Tests that need WeasyPrint's native libraries skip cleanly when those
libraries aren't installed, so the suite runs anywhere.

### Building and publishing a release

The version is single-sourced from `src/prototyper/__init__.py`. To cut a
release, bump `__version__` there, then:

```sh
pip install build twine
python -m build            # writes sdist + wheel to dist/
twine check dist/*         # validate metadata renders on PyPI
twine upload dist/*        # requires PyPI credentials
```

## License

[MIT](LICENSE)
