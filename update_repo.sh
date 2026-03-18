#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_NAME="${1:-origin}"
BACKUP_DIR="$(mktemp -d /tmp/tubesplitter-update.XXXXXX)"
BACKUP_ARCHIVE="$BACKUP_DIR/ignored-backup.tar"
MANIFEST_FILE="$BACKUP_DIR/ignored-paths.txt"
BACKUP_CREATED=false

cleanup() {
    if [ "$BACKUP_CREATED" = true ] && [ -d "$BACKUP_DIR" ]; then
        echo "Backup is still available at: $BACKUP_DIR"
    fi
}

trap cleanup EXIT

cd "$PROJECT_DIR"

if ! command -v git >/dev/null 2>&1; then
    echo "git is required but was not found."
    exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
    echo "tar is required but was not found."
    exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "This script must run inside the TubeSplitter git repository."
    exit 1
fi

if command -v pgrep >/dev/null 2>&1 && pgrep -af "python(3)? .*main\.py" >/dev/null; then
    echo "The bot appears to be running. Stop it before running ./update_repo.sh."
    exit 1
fi

if ! git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
    echo "Git remote '$REMOTE_NAME' was not found."
    exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
    echo "Detached HEAD is not supported. Checkout a branch before updating."
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Tracked local changes detected. Commit or stash them before updating."
    exit 1
fi

PREVIOUS_COMMIT="$(git rev-parse HEAD)"

mapfile -t IGNORED_PATHS < <(
    git ls-files --others -i --exclude-standard --directory |
        while IFS= read -r path; do
            case "$path" in
                __pycache__/|*/__pycache__/|*.pyc)
                    continue
                    ;;
            esac
            printf '%s\n' "$path"
        done
)

if [ "${#IGNORED_PATHS[@]}" -gt 0 ]; then
    printf '%s\n' "${IGNORED_PATHS[@]}" > "$MANIFEST_FILE"
    tar -cpf "$BACKUP_ARCHIVE" -C "$PROJECT_DIR" --files-from "$MANIFEST_FILE"
    BACKUP_CREATED=true
    echo "Backed up ${#IGNORED_PATHS[@]} ignored path(s)."
else
    : > "$MANIFEST_FILE"
    echo "No ignored paths were found to back up."
fi

git fetch "$REMOTE_NAME"
git pull --ff-only "$REMOTE_NAME" "$CURRENT_BRANCH"
UPDATED_COMMIT="$(git rev-parse HEAD)"
echo "Previous commit: $PREVIOUS_COMMIT"
echo "Current commit:  $UPDATED_COMMIT"

if [ -s "$MANIFEST_FILE" ]; then
    tar -xpf "$BACKUP_ARCHIVE" -C "$PROJECT_DIR"
    echo "Restored ignored path(s) from backup."
fi

if [ "$PREVIOUS_COMMIT" != "$UPDATED_COMMIT" ] && ! git diff --quiet "$PREVIOUS_COMMIT" "$UPDATED_COMMIT" -- requirements.txt; then
    if [ ! -d "$PROJECT_DIR/.venv" ]; then
        echo "requirements.txt changed, but the virtual environment is missing. Run ./setup.sh first."
        exit 1
    fi

    echo "requirements.txt changed. Updating dependencies..."
    source "$PROJECT_DIR/.venv/bin/activate"
    python -m pip install -r "$PROJECT_DIR/requirements.txt"
else
    echo "requirements.txt did not change. Skipping dependency install."
fi

rm -rf "$BACKUP_DIR"
BACKUP_CREATED=false

if [ "$PREVIOUS_COMMIT" = "$UPDATED_COMMIT" ]; then
    echo "Already up to date."
fi

echo "Update complete. You can start the bot again with ./run_bot.sh."
