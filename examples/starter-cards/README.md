# Starter cards example

A minimal, working `prototyper` project you can copy as a starting point.
It defines six poker-sized cards from a CSV and an HTML/CSS template.

## Layout

```
starter-cards/
  project.yaml          # ties it together: component size, data + template paths, layout
  data/
    cards.csv           # one row per card; headers -> template placeholders
  templates/
    card.html           # the card design, rendered once per row
```

(A real project may also have an `assets/` folder for images and fonts,
referenced from the template by relative path. This example is asset-free
so it builds anywhere with no extra files.)

## Build it

From the repository root:

```sh
prototyper build examples/starter-cards
```

The print-ready PDF is written to
`examples/starter-cards/build/starter-cards.pdf` — a single 8.5x11 sheet
layout with the six cards auto-packed into a grid and thin cut lines for
home trimming.

## Iterate on it

Watch mode gives a live browser preview of one card plus an automatic PDF
rebuild whenever you save a change to the data or template:

```sh
prototyper watch examples/starter-cards
```

Record why you made a design change so future-you (or a collaborator) can
follow the reasoning:

```sh
prototyper note "bumped Ancient Dragon to 7 cost — it was dominating" examples/starter-cards
```

## Make it yours

- Add or edit rows in `data/cards.csv`. Each row becomes one card.
- Add a column, then reference it in `templates/card.html` as
  `{{ column_name }}`. Every placeholder must have a matching column, or
  the build fails loudly (use `{{ column_name | default('') }}` for
  optional fields).
- Change the component size in `project.yaml` — pick another preset
  (`bridge`, `tarot`, `mini`, `hex-token`, `square-token`) or set an
  explicit `width`/`height`.
