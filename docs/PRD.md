# PRD: Board/Card Game Component Print Tool

*Status: Draft v1 — placeholder name, subject to change.*

## Summary

A Python CLI tool for indie/hobbyist tabletop game designers that generates
print-ready 8.5x11 PDF sheets from HTML/CSS component templates and CSV data.
Designed to replace ad hoc use of tools like nanDeck/Squib with a simpler,
standards-based approach: HTML/CSS for design instead of a bespoke scripting
language.

## Goals

- Let a designer define one card/board/token component as an HTML/CSS
  template, feed it a CSV of rows, and get a paginated, print-ready PDF.
- Fast iteration loop: live browser preview of a single component, plus a
  watch mode that rebuilds the full PDF on file changes.
- Sensible defaults (standard component size presets, auto-grid page
  packing, cut lines) so a first project works with minimal configuration.
- Ship as a real, pip-installable package with a console-script CLI.
- Persist a structured history of a project's iterations (builds and
  designer rationale) so a designer can pick up an old project and
  understand how and why it evolved, and so the same history can later
  feed an AI-assisted design feature.

## Non-goals (v1)

- Double-sided/duplex printing (front/back alignment). Single-sided only
  for v1; revisit once the core single-sided pipeline is proven.
- True print-shop bleed/crop marks for services like The Game Crafter.
  Cut *lines* for home trimming are in scope; bleed margins/registration
  marks for commercial printing are not.
- Combining multiple component types (e.g. cards + board + tokens) into
  one output. v1 is one component type per project run; combine outputs
  by running the tool multiple times. Flagged as a strong v2 candidate.

## Target user

Indie/hobbyist tabletop game designers who are comfortable with a CLI and
with basic HTML/CSS, prototyping physical card/board/token components for
home printing.

## Core concepts

- **Project**: a convention-based folder containing the component
  template, its data, and its assets, tied together by a project config
  file.
- **Component**: a single design (card, board, or token) defined once as
  an HTML/CSS template and instantiated once per row of input data.
- **Sheet**: an 8.5x11 output page containing an auto-packed grid of
  rendered components.

### Project folder convention

```
my-project/
  project.yaml       # ties everything together: component size, data path, template path
  data/
    cards.csv         # one row per component instance
  templates/
    card.html          # HTML/CSS template with data placeholders
  assets/
    fonts/              # custom font files, referenced via CSS
    images/              # local images referenced by the template
  .prototyper/
    history.yaml         # tool-managed build + rationale log (see Design memory)
```

## Functional requirements

### Input

- **Data**: CSV, one row per component instance. Column headers map to
  template placeholders.
- **Template**: HTML + CSS. Data fields are injected via a standard
  Python templating engine (e.g. Jinja2) — no custom scripting language.
- **Assets**: images and fonts referenced from the project's `/assets`
  folder via relative paths; system-installed fonts may also be
  referenced via CSS `font-family` for quick prototyping (not embedded/
  guaranteed portable across machines).

### Component sizing

- Ship standard presets (e.g. poker 2.5x3.5in, bridge, tarot, hex token,
  square token) selectable by name in the project config.
- Allow fully custom width/height (and shape, where relevant) as an
  override.

### Page layout

- Auto-grid packing: the tool computes how many components fit per
  8.5x11 sheet given component size and fills sheets in data order.
- Layout hints: designer can control margins, gutter/spacing between
  components, and force page breaks (e.g. between logical groups of
  cards).
- Cut lines: thin registration lines are drawn between/around components
  on the sheet to guide scissor/paper-cutter trimming. Not bleed —
  content is not extended past the trim line.

### Output

- A single multi-page PDF sized for 8.5x11, one PDF per CLI build run.

### CLI workflow

- `build`: renders the project's data + template into the final paginated
  PDF. Also appends an automatic entry to the project's history log (see
  Design memory below).
- `watch`: re-renders on file change, combining two feedback loops:
  - **Live browser preview** of a single rendered component (fast
    styling iteration, not paginated).
  - **PDF rebuild trigger** to check true final page layout/packing.
- `note "<message>"`: attaches a designer-written rationale entry to the
  history log, associated with the most recent build (or standalone if
  no build has happened yet).

### Design memory (iteration history)

Goal: a designer can open an old project — or hand it to someone else —
and understand not just *what* the current design is, but how it got
there and why, without needing to archaeology through git log or file
diffs.

- **Storage**: a single tool-managed log at `.prototyper/history.yaml`,
  one per project (not per component). Independent of whether the
  designer also uses git — this is a lighter-weight, tool-native
  complement, not a replacement for git.
- **Automatic entries**: every `build` run appends an entry capturing at
  minimum a timestamp, a content hash of the template/data/config
  inputs, and the output PDF path. Cheap, zero-effort, gives a build/
  output history for free.
- **Manual entries**: the `note` command lets the designer attach free-
  text rationale (e.g. "lowered this card's cost from 3 to 2 for
  balance") to a point in that history — this is the part plain file
  diffs or git commit messages don't capture well for a non-technical
  audience, and the part most worth getting right.
- **Format**: structured (YAML), so it's both human-readable (a designer
  can open and read it directly as a changelog) and machine-readable —
  laying groundwork for a future AI-assisted feature to consume it as
  context (see Future scope). No AI-powered commands ship in v1; v1 is
  about getting the structure right.

### Distribution

- Published to PyPI, installable via `pip`/`pipx`, with a console-script
  entry point (placeholder command name TBD).

## Open questions / to finalize later

- Final tool/package/CLI name.
- Exact PDF rendering library (e.g. WeasyPrint) and templating engine
  (e.g. Jinja2) — implementation detail, not blocking PRD approval.
- Exact set of size presets to ship in v1.
- Cut line styling (dash pattern, color, weight) defaults.
- Exact schema of `.prototyper/history.yaml` entries (auto vs. manual
  fields, how notes attach to a specific build entry vs. standalone).

## Future scope (explicitly out of v1, revisit later)

- Multi-component projects: combine cards, boards, and tokens into a
  single print output from one project config.
- Double-sided/duplex printing with front/back alignment.
- Print-shop bleed and crop marks for commercial print-on-demand
  services.
- AI-assisted design commands that read `.prototyper/history.yaml` to
  give context-aware suggestions (e.g. "you tried a similar layout in
  iteration 4 and reverted it — here's what changed").
