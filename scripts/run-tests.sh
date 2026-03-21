#!/usr/bin/env bash
# run-tests.sh — Run all test suites for AgentOS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== AgentOS Test Runner ==="

FAILED=0

# Backend tests
echo ""
echo "--- Backend Tests ---"
if (cd "$ROOT_DIR/backend" && python -m pytest tests/ -v --tb=short -x 2>&1); then
    echo "[ok] Backend tests passed"
else
    echo "[FAIL] Backend tests failed"
    FAILED=1
fi

# SDK tests
echo ""
echo "--- SDK Tests ---"
if (cd "$ROOT_DIR/sdk" && python -m pytest tests/ -v --tb=short -x 2>&1); then
    echo "[ok] SDK tests passed"
else
    echo "[FAIL] SDK tests failed"
    FAILED=1
fi

# Frontend lint (if available)
echo ""
echo "--- Frontend Lint ---"
if [ -f "$ROOT_DIR/frontend/package.json" ]; then
    if (cd "$ROOT_DIR/frontend" && npm run lint 2>&1); then
        echo "[ok] Frontend lint passed"
    else
        echo "[FAIL] Frontend lint failed"
        FAILED=1
    fi
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "=== All tests passed ==="
else
    echo "=== Some tests failed ==="
    exit 1
fi
