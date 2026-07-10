# Project instructions

This is a Python CLI tool that helps build board/card game components,
lays them out on 8.5x11 pages, and outputs print-ready PDFs.

- Full requirements: `docs/PRD.md`
- Build task list: `docs/tasklist.md`
- Development progress log: `docs/progress.txt`

## Default workflow

When asked to work on the project without a more specific instruction,
follow this loop:

1. **Load context** — read `docs/PRD.md` for requirements and
   constraints before making design decisions.
2. **Pick the next task** — read `docs/tasklist.md` top to bottom and
   take the first unchecked (`- [ ]`) item. Tasks are ordered by
   dependency, so don't skip ahead.
3. **Verify it isn't already done** — check the current code/tests
   before starting; if the task turns out to already be complete, check
   its box and move to the next one instead of redoing work.
4. **Implement using TDD** — write a failing test for the behavior the
   task describes, write the minimum code to make it pass, then refactor.
   Don't write implementation code without a preceding failing test.
5. **Verify completion** — run the test suite (and any other relevant
   checks) to confirm the task's behavior works and nothing else broke.
   Only then check the box in `docs/tasklist.md` for that task and
   append an entry to `docs/progress.txt` (see its header for format)
   summarizing what changed and the rationale behind the approach taken.

If a task is too large or vague to implement directly, break it into
smaller checklist items in `docs/tasklist.md` in place, then proceed
with the first one.
