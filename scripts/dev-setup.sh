#!/usr/bin/env bash
# dev-setup.sh — Bootstrap the development environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== AgentOS Dev Setup ==="

# 1. Create .env from example if missing
if [ ! -f "$ROOT_DIR/.env" ]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    echo "[ok] Created .env from .env.example — fill in your API keys"
else
    echo "[skip] .env already exists"
fi

# 2. Install backend dependencies
if command -v pip &>/dev/null; then
    echo "[...] Installing backend dependencies"
    pip install -r "$ROOT_DIR/backend/requirements.txt" -q
    echo "[ok] Backend dependencies installed"
fi

# 3. Install frontend dependencies
if command -v npm &>/dev/null && [ -f "$ROOT_DIR/frontend/package.json" ]; then
    echo "[...] Installing frontend dependencies"
    (cd "$ROOT_DIR/frontend" && npm install --silent)
    echo "[ok] Frontend dependencies installed"
fi

# 4. Install SDK in editable mode
if [ -f "$ROOT_DIR/sdk/pyproject.toml" ]; then
    echo "[...] Installing SDK in editable mode"
    pip install -e "$ROOT_DIR/sdk" -q
    echo "[ok] SDK installed"
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Fill in API keys in .env"
echo "  2. Run: docker compose up -d"
echo "  3. Or for backend only: cd backend && uvicorn api.main:app --reload"
