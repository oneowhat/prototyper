#!/usr/bin/env bash
set -euo pipefail

# Resolves a secret from <VAR>_FILE (a mounted read-only file) if set,
# otherwise falls back to <VAR> directly. Preferring the file form keeps
# the value out of `docker inspect`/`ps` output.
resolve_secret() {
    local var_name="$1"
    local file_var="${var_name}_FILE"
    local file_path="${!file_var:-}"
    if [ -n "$file_path" ]; then
        if [ ! -r "$file_path" ]; then
            echo "[entrypoint] ${file_var}=${file_path} is not readable" >&2
            exit 1
        fi
        cat "$file_path"
    else
        printf '%s' "${!var_name:-}"
    fi
}

ANTHROPIC_API_KEY="$(resolve_secret ANTHROPIC_API_KEY)"
GITHUB_TOKEN="$(resolve_secret GITHUB_TOKEN)"
export ANTHROPIC_API_KEY

: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY or ANTHROPIC_API_KEY_FILE}"
: "${GITHUB_TOKEN:?set GITHUB_TOKEN or GITHUB_TOKEN_FILE (repo-scoped PAT with contents:write)}"

GITHUB_REPO="${GITHUB_REPO:-oneowhat/prototyper}"
BRANCH="${BRANCH:-autonomous/build-v1}"
MAX_ITERS="${MAX_ITERS:-20}"
WORKDIR="/workspace/repo"
OUT_DIR="${OUT_DIR:-/workspace/out}"

# Regardless of whether `git push` actually succeeds, write a bundle of
# the current branch to a host-mounted directory (if one was given via
# -v ...:/workspace/out). This is the recovery path when push fails or
# the run is otherwise interrupted: the container's own filesystem
# disappears on exit (usually run with --rm), so this bundle mount is
# the only thing that survives that.
backup_branch() {
    if [ -d "$OUT_DIR" ] && [ -w "$OUT_DIR" ]; then
        local bundle="$OUT_DIR/${BRANCH//\//-}.bundle"
        git bundle create "$bundle" "$BRANCH" >/dev/null
        echo "[entrypoint] Backed up '$BRANCH' to $bundle"
    else
        echo "[entrypoint] WARNING: no writable backup dir at $OUT_DIR" \
             "(mount one with -v <host-dir>:$OUT_DIR) — if the push below" \
             "fails, this commit only exists in the container and will be" \
             "lost when it exits." >&2
    fi
}

# Confirms HEAD actually reached the remote branch — don't just trust
# claude's own report of whether `git push` succeeded.
verify_pushed() {
    local remote_head local_head
    remote_head="$(git ls-remote origin "refs/heads/$BRANCH" | cut -f1)"
    local_head="$(git rev-parse HEAD)"
    if [ "$remote_head" != "$local_head" ]; then
        echo "[entrypoint] WARNING: local HEAD ($local_head) is not published" \
             "to origin/$BRANCH (remote has '${remote_head:-nothing}')." \
             "Recover it from the backup bundle above." >&2
        return 1
    fi
}

git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git" "$WORKDIR"
cd "$WORKDIR"
git config user.name "Autonomous Build Agent"
git config user.email "agent@localhost"

# Continue an existing run on this branch if one exists remotely,
# otherwise branch fresh off the default branch.
git fetch origin "$BRANCH" 2>/dev/null || true
if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    git checkout -B "$BRANCH" "origin/$BRANCH"
else
    git checkout -B "$BRANCH"
fi

TASK_PROMPT='Follow the default workflow in CLAUDE.md to complete exactly one
task from docs/tasklist.md, then stop — do not start a second task. After
committing, run `git push -u origin HEAD` to publish the commit.'

for i in $(seq 1 "$MAX_ITERS"); do
    if ! grep -q '^- \[ \]' docs/tasklist.md; then
        echo "[entrypoint] All tasks in docs/tasklist.md are checked off. Done."
        exit 0
    fi

    before="$(md5sum docs/tasklist.md)"

    if ! claude --dangerously-skip-permissions -p "$TASK_PROMPT"; then
        echo "[entrypoint] claude exited non-zero on iteration $i" >&2
    fi

    # Always back up and verify, regardless of how the above went — this
    # is the whole point of the safety net.
    backup_branch
    verify_pushed || true

    after="$(md5sum docs/tasklist.md)"
    if [ "$before" = "$after" ]; then
        echo "[entrypoint] No progress on iteration $i (tasklist.md unchanged)." \
             "Stopping to avoid a runaway loop — check the branch '$BRANCH' for what happened."
        exit 1
    fi
done

echo "[entrypoint] Hit MAX_ITERS=$MAX_ITERS without finishing the task list." \
     "Re-run the container to continue from where it left off."
