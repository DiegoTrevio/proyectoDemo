#!/usr/bin/env bash
# health-check.sh — Verify all AgentOS services are healthy.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check() {
    local name="$1" url="$2"
    if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name"
    else
        echo -e "  ${RED}✗${NC} $name ($url)"
        FAILED=1
    fi
}

FAILED=0

echo "=== AgentOS Health Check ==="
echo ""
echo "Core services:"
check "Backend (FastAPI)"       "http://localhost:8000/health"
check "LiteLLM (LLM Router)"   "http://localhost:4000/health"
check "Redis"                   "http://localhost:6379" 2>/dev/null || true

echo ""
echo "Databases:"
check "PostgreSQL"              "http://localhost:5432" 2>/dev/null || true

echo ""
echo "Optional services:"
check "Frontend (Next.js)"      "http://localhost:3000"
check "Langfuse (Observability)" "http://localhost:3001/api/public/health"
check "LLM Guard (Security)"   "http://localhost:8080/health"
check "Letta (Memory)"         "http://localhost:8283/v1/health"
check "SuperTokens (Auth)"     "http://localhost:3567/hello"

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}All services healthy.${NC}"
else
    echo -e "${YELLOW}Some services are down. Run 'docker compose ps' to investigate.${NC}"
fi
