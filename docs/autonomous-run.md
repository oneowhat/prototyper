# Running the build agent autonomously in Docker

This runs Claude Code unattended, with permission prompts bypassed
(`--dangerously-skip-permissions`), working through `docs/tasklist.md`
one task at a time per `CLAUDE.md`'s default workflow. It's safe to grant
full permissions because the container is the sandbox boundary: it never
mounts your local checkout, it clones its own fresh copy from GitHub and
only talks back to the outside world by pushing commits to a branch.

## One-time setup

1. **Create a scoped GitHub token.** On GitHub: Settings → Developer
   settings → Fine-grained personal access tokens → Generate new token.
   - Repository access: only `oneowhat/prototyper`.
   - Permissions: Contents → Read and write. Nothing else.
   - This limits the blast radius if the token ever leaks — it can't
     touch your other repos or account settings.
2. Have an `ANTHROPIC_API_KEY` available (from the Anthropic Console).

Keep both out of shell history / files that get committed — pass them as
environment variables at run time (see below).

## Build the image

```sh
docker build -t prototyper-agent .
```

## Run it

```sh
docker run --rm \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e GITHUB_TOKEN="$GITHUB_TOKEN" \
  prototyper-agent
```

Optional environment variables:

- `BRANCH` — branch to push to (default `autonomous/build-v1`). The
  container force-creates this branch locally each run; the push still
  requires a fast-forward on the remote unless you delete it there too.
- `MAX_ITERS` — safety cap on how many tasks to attempt in one run
  (default `20`). The loop also stops early if a task makes no progress
  (tasklist.md unchanged), so it can't spin forever burning API credits.

## Reviewing the result

Nothing touches your local disk until you decide to look. From your host:

```sh
git fetch origin
git log origin/autonomous/build-v1
```

Open a PR from that branch (or diff it locally) when you're ready to
merge into `main`. Re-running the container continues from the current
state of `docs/tasklist.md` on that branch — pass the same `BRANCH` value
and it'll pick up where it left off; running with a fresh default branch
name starts the task list over from `main`.
