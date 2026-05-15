#!/usr/bin/env bash
# AegisNotes — first-time Raspberry Pi setup.
#
# Run as a non-root user that owns the repo, e.g.:
#
#     cd ~/AegisNotes && bash scripts/setup_pi.sh
#
# Idempotent. Skips steps that have already been performed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PY="${PYTHON:-python3}"

echo "==> Repo:     ${REPO_ROOT}"
echo "==> venv:     ${VENV_DIR}"
echo "==> Python:   $(${PY} --version)"

# ---------------------------------------------------------------------------
# System packages (Phase 1 only needs libmagic + tesseract for forward compat).
# We use --no-install-recommends to keep the SD card image small.
# ---------------------------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    echo "==> Installing system packages (sudo)…"
    sudo apt-get update
    sudo apt-get install --no-install-recommends -y \
        python3 python3-venv python3-pip \
        libmagic1 \
        tesseract-ocr tesseract-ocr-eng \
        poppler-utils \
        libgl1 libglib2.0-0 \
        libjpeg-dev zlib1g-dev libpng-dev libtiff-dev libwebp-dev
else
    echo "==> apt-get not found; skipping system package install."
fi

# ---------------------------------------------------------------------------
# Python virtual environment
# ---------------------------------------------------------------------------
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "==> Creating virtual environment…"
    "${PY}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "==> Upgrading pip…"
pip install --upgrade pip wheel

echo "==> Installing Python dependencies…"
pip install -r "${REPO_ROOT}/requirements.txt"

# ---------------------------------------------------------------------------
# .env bootstrap
# ---------------------------------------------------------------------------
if [[ ! -f "${REPO_ROOT}/.env" ]]; then
    echo "==> Generating .env from .env.example…"
    cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
    SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    sed -i "s|^AEGIS_SECRET_KEY=.*|AEGIS_SECRET_KEY=${SECRET}|" "${REPO_ROOT}/.env"
    echo "==> Wrote a fresh AEGIS_SECRET_KEY into .env."
fi

# ---------------------------------------------------------------------------
# Initialize database
# ---------------------------------------------------------------------------
echo "==> Initializing database…"
python "${REPO_ROOT}/scripts/init_db.py"

# ---------------------------------------------------------------------------
# Create first admin if no users exist
# ---------------------------------------------------------------------------
EXISTING_USERS=$(python - <<'PY'
from src.database.repositories import UsersRepository
print(UsersRepository().count())
PY
)
if [[ "${EXISTING_USERS}" == "0" ]]; then
    echo "==> No users yet — creating the first admin account."
    read -rp "Admin username: " ADMIN_USER
    python "${REPO_ROOT}/scripts/create_user.py" "${ADMIN_USER}" --admin
fi

echo
echo "==> Setup complete."
echo "    Activate the venv:  source ${VENV_DIR}/bin/activate"
echo "    Run the dev server: bash scripts/run_dev.sh"
echo "    Install as service: see scripts/aegisnotes.service"
