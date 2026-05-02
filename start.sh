#!/usr/bin/env bash
# start.sh — convenience wrapper to start the budget-ai stack
#
# Usage:
#   ./start.sh            # start in foreground (logs visible)
#   ./start.sh -d         # start detached (background)
#   ./start.sh --model phi3:mini  # use a different model
set -euo pipefail

MODEL="${DEFAULT_MODEL:-tinyllama}"
DETACH=""
SELECTED_MODEL="$MODEL"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--detach)
      DETACH="-d"
      shift
      ;;
    --model)
      SELECTED_MODEL="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [-d] [--model <model_name>]"
      exit 1
      ;;
  esac
done

# Write a .env file from .env.example if one doesn't exist yet
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

export DEFAULT_MODEL="$SELECTED_MODEL"

echo "Starting budget-ai stack with model: $SELECTED_MODEL"
docker compose up --build $DETACH
