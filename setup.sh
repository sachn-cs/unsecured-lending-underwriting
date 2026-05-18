#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
DATA_DIR="${ULU_DATA_DIR:-./data}"

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-ulu}"
DB_USER="${DB_USER:-ulu}"
DB_PASS="${DB_PASS:-ulu}"

ALGOD_URL="${ALGOD_URL:-http://localhost:4001}"
ALGOD_TOKEN="${ALGOD_TOKEN:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}"

echo "=== ULU Setup ==="
echo "Python: ${PYTHON}"
echo "Venv:   ${VENV_DIR}"
echo "Data:   ${DATA_DIR}"
echo "DB:     ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "Algod:  ${ALGOD_URL}"
echo ""

# ------------------------------------------------------------------
# 1. Virtual environment
# ------------------------------------------------------------------
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[1/7] Creating virtual environment..."
    "${PYTHON}" -m venv "${VENV_DIR}"
else
    echo "[1/7] Virtual environment already exists."
fi

source "${VENV_DIR}/bin/activate"

# ------------------------------------------------------------------
# 2. Core dependencies
# ------------------------------------------------------------------
echo "[2/7] Installing dependencies..."
pip install -e ".[dev,api,risk,blockchain]" >/dev/null

# ------------------------------------------------------------------
# 3. Data directory
# ------------------------------------------------------------------
echo "[3/7] Creating data directory..."
mkdir -p "${DATA_DIR}"

# ------------------------------------------------------------------
# 4. PostgreSQL readiness check
# ------------------------------------------------------------------
echo "[4/7] Checking PostgreSQL connectivity..."
if command -v pg_isready >/dev/null 2>&1; then
    if pg_isready -h "${DB_HOST}" -p "${DB_PORT}" >/dev/null 2>&1; then
        echo "      PostgreSQL is reachable."
    else
        echo "      WARNING: PostgreSQL not reachable at ${DB_HOST}:${DB_PORT}"
        echo "      Skipping database creation."
    fi
else
    echo "      WARNING: pg_isready not found. Cannot verify PostgreSQL."
fi

# ------------------------------------------------------------------
# 5. Database creation (best-effort)
# ------------------------------------------------------------------
echo "[5/7] Ensuring database exists..."
if command -v psql >/dev/null 2>&1; then
    export PGPASSWORD="${DB_PASS}"
    if psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT 1;" >/dev/null 2>&1; then
        echo "      Database ${DB_NAME} already exists."
    else
        if psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME};" >/dev/null 2>&1; then
            echo "      Created database ${DB_NAME}."
        else
            echo "      WARNING: Could not create database ${DB_NAME}."
            echo "      Ensure PostgreSQL is running and credentials are correct."
        fi
    fi
else
    echo "      WARNING: psql not found. Skipping database creation."
fi

# ------------------------------------------------------------------
# 6. Environment file
# ------------------------------------------------------------------
echo "[6/7] Writing .env file..."
cat > .env <<EOF
DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}
ALGOD_URL=${ALGOD_URL}
ALGOD_TOKEN=${ALGOD_TOKEN}
ULU_DATA_DIR=${DATA_DIR}
ULU_ADMIN_TOKEN=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
APP_ENV=development
LOG_LEVEL=INFO
EOF

# ------------------------------------------------------------------
# 7. Verification
# ------------------------------------------------------------------
echo "[7/7] Verifying installation..."
if PYTHONPATH="${SCRIPT_DIR}" python -c "from ulu import DelegatedUnderwriting; print('      Import OK')"; then
    echo ""
    echo "=== Setup complete ==="
    echo "Activate venv: source ${VENV_DIR}/bin/activate"
    echo "Run tests:     PYTHONPATH=. pytest -q"
    echo "Run demo:      PYTHONPATH=. python demo.py run-demo"
    echo "Start API:     PYTHONPATH=. uvicorn ulu.api.app:app --reload"
    echo ""
else
    echo "      ERROR: Import verification failed."
    exit 1
fi
