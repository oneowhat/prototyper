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

    claude --dangerously-skip-permissions -p "$TASK_PROMPT"

    after="$(md5sum docs/tasklist.md)"
    if [ "$before" = "$after" ]; then
        echo "[entrypoint] No progress on iteration $i (tasklist.md unchanged)." \
             "Stopping to avoid a runaway loop — check the branch '$BRANCH' for what happened."
        exit 1
    fi
done

echo "[entrypoint] Hit MAX_ITERS=$MAX_ITERS without finishing the task list." \
     "Re-run the container to continue from where it left off."
