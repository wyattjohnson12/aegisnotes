#!/usr/bin/env bash
# AegisNotes — local development runner.
#
# Activates the venv, applies migrations, then starts uvicorn with auto-reload.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
    echo "Virtual environment not found. Run scripts/setup_pi.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

cd "${REPO_ROOT}"

python scripts/init_db.py

HOST="${AEGIS_HOST:-0.0.0.0}"
PORT="${AEGIS_PORT:-8000}"

echo "==> Starting uvicorn on ${HOST}:${PORT} (reload enabled)"
exec uvicorn src.main:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --reload \
    --reload-dir src \
    --reload-dir frontend \
    --reload-dir config
