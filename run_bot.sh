#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"

cd "$PROJECT_DIR"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment is missing. Run ./setup.sh first."
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo ".env is missing. Create it or run ./setup.sh first."
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ "$TELEGRAM_BOT_TOKEN" = "replace_me" ]; then
    echo "Set TELEGRAM_BOT_TOKEN in .env before running the bot."
    exit 1
fi

source "$VENV_DIR/bin/activate"
exec python main.py
