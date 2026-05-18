#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

VENV_DIR="${VENV_DIR:-.venv}"
DATA_DIR="${ULU_DATA_DIR:-./data}"
DB_NAME="${DB_NAME:-ulu}"
DB_USER="${DB_USER:-ulu}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_PASS="${DB_PASS:-ulu}"

echo "=== ULU Cleanup ==="
read -r -p "This will remove the venv, data directory, and database. Continue? [y/N] " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

# ------------------------------------------------------------------
# 1. Remove virtual environment
# ------------------------------------------------------------------
if [[ -d "${VENV_DIR}" ]]; then
    echo "[1/5] Removing virtual environment..."
    rm -rf "${VENV_DIR}"
else
    echo "[1/5] Virtual environment not found."
fi

# ------------------------------------------------------------------
# 2. Remove data directory
# ------------------------------------------------------------------
if [[ -d "${DATA_DIR}" ]]; then
    echo "[2/5] Removing data directory..."
    rm -rf "${DATA_DIR}"
else
    echo "[2/5] Data directory not found."
fi

# ------------------------------------------------------------------
# 3. Remove .env file
# ------------------------------------------------------------------
if [[ -f ".env" ]]; then
    echo "[3/5] Removing .env file..."
    rm -f ".env"
else
    echo "[3/5] .env file not found."
fi

# ------------------------------------------------------------------
# 4. Drop PostgreSQL database (best-effort)
# ------------------------------------------------------------------
echo "[4/5] Dropping PostgreSQL database (best-effort)..."
if command -v psql >/dev/null 2>&1; then
    export PGPASSWORD="${DB_PASS}"
    if psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};" >/dev/null 2>&1; then
        echo "      Dropped database ${DB_NAME}."
    else
        echo "      WARNING: Could not drop database ${DB_NAME}."
        echo "      You may need to drop it manually:"
        echo "        psql -U ${DB_USER} -d postgres -c 'DROP DATABASE ${DB_NAME};'"
    fi
else
    echo "      WARNING: psql not found. Skipping database drop."
fi

# ------------------------------------------------------------------
# 5. Remove __pycache__ and .pyc files
# ------------------------------------------------------------------
echo "[5/5] Removing Python cache files..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "=== Cleanup complete ==="
echo "To rebuild: ./setup.sh"
echo ""
