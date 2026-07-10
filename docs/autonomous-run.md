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
3. **Store both in macOS Keychain** rather than a plaintext file at
   rest. The trailing `-w` with no value makes `security` prompt
   interactively for the secret, so it never touches shell history:

   ```sh
   security add-generic-password -a "$USER" -s "prototyper-anthropic-api-key" -w
   security add-generic-password -a "$USER" -s "prototyper-github-token" -w
   ```

   (Add `-U` to update an existing entry instead of erroring on a
   duplicate; `security delete-generic-password -a "$USER" -s <service>`
   to remove one.)

Keep both out of shell history and out of anything that gets committed.

## Build the image

```sh
docker build -t prototyper-agent .
```

## Run it

Prefer mounting secrets as read-only files over passing them as `-e`
values. `-e KEY=value` on the command line lands in shell history and is
readable in plaintext via `docker inspect`/`docker top` by anyone with
Docker daemon access; a file mount only exposes a path in that metadata.

Pull the values out of Keychain and into the mounted files at run
time, rather than keeping them in a plaintext file at rest:

```sh
mkdir -p ~/.secrets/prototyper
chmod 700 ~/.secrets/prototyper

security find-generic-password -a "$USER" -s prototyper-anthropic-api-key -w \
  > ~/.secrets/prototyper/anthropic_api_key
security find-generic-password -a "$USER" -s prototyper-github-token -w \
  > ~/.secrets/prototyper/github_token
chmod 600 ~/.secrets/prototyper/*

docker run --rm \
  -v ~/.secrets/prototyper:/run/secrets:ro \
  -e ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_api_key \
  -e GITHUB_TOKEN_FILE=/run/secrets/github_token \
  prototyper-agent

rm -f ~/.secrets/prototyper/anthropic_api_key ~/.secrets/prototyper/github_token
```

Other secrets managers (1Password CLI, `pass`, etc.) work the same way —
just swap the `security find-generic-password` calls for the equivalent
read command, e.g. `op read op://vault/anthropic/key`.

Passing `-e ANTHROPIC_API_KEY=...` / `-e GITHUB_TOKEN=...` directly still
works as a fallback (`entrypoint.sh` checks the `_FILE` variables first),
but the file-mount form above is the recommended default.

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
