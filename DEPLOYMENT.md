# AgentOS — Production Deployment Guide

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Domain with DNS configured (e.g. `app.yourdomain.com`)
- SSL certificate (or use Let's Encrypt with a reverse proxy)
- API keys: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `E2B_API_KEY`

## Quick Start (Development)

```bash
cp .env.example .env
# Edit .env with your API keys
make up
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# API Docs: http://localhost:8000/docs
```

## Production Deployment

### 1. Configure Environment Variables

```bash
cp .env.example .env
```

**Required changes for production:**

```bash
# URLs — set to your actual domain
FRONTEND_URL=https://app.yourdomain.com
BACKEND_URL=https://api.yourdomain.com
CORS_ORIGINS=https://app.yourdomain.com

# Security — MUST change these
API_KEY_SALT=$(openssl rand -hex 32)
MANIFEST_SIGNING_KEY=$(openssl rand -hex 32)

# Database — use strong passwords
POSTGRES_PASSWORD=$(openssl rand -base64 24)
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@postgres:5432/agentOS
NEO4J_PASSWORD=$(openssl rand -base64 24)

# Stripe (if billing enabled)
STRIPE_SECRET_KEY=sk_live_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# Frontend
NEXT_PUBLIC_API_URL=https://api.yourdomain.com/api/v1
NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com
NEXT_PUBLIC_URL=https://app.yourdomain.com
```

### 2. Deploy Services

```bash
# Build and start all services
make up

# Run database migrations
make migrate

# Verify health
make health
```

### 3. Verify Deployment

```bash
# Backend health
curl https://api.yourdomain.com/health

# API documentation
# Open https://api.yourdomain.com/docs in browser

# Frontend
# Open https://app.yourdomain.com in browser
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│   Frontend   │────▶│   Backend    │────▶│  PostgreSQL │
│  (Next.js)   │     │  (FastAPI)   │     └────────────┘
│  port 3000   │     │  port 8000   │     ┌────────────┐
└─────────────┘     │              │────▶│   Redis     │
                    │              │     └────────────┘
                    │              │     ┌────────────┐
                    │              │────▶│   Neo4j     │
                    └──────┬───────┘     └────────────┘
                           │
                    ┌──────▼───────┐
                    │  arq Worker  │
                    │ (task queue) │
                    └──────────────┘
```

**Additional services** (all self-hosted, no external cost):
- **LiteLLM** — LLM proxy with model routing and fallbacks
- **Langfuse** — Observability and tracing
- **LLM Guard** — Input/output security scanning
- **SuperTokens** — Authentication (email, OAuth)
- **DeerFlow** — Deep research sub-agent

## Environment Variable Reference

### Required API Keys

| Variable | Purpose | Cost |
|----------|---------|------|
| `ANTHROPIC_API_KEY` | Claude Opus + Sonnet (orchestrator + workhorse) | ~$30/mo |
| `GOOGLE_API_KEY` | Gemini Flash (cheap tier + fallback) | ~$5/mo |
| `TAVILY_API_KEY` | Web search for research agent | ~$20/mo |
| `E2B_API_KEY` | Code execution sandboxes | ~$10/mo |
| `LITELLM_MASTER_KEY` | Internal LLM router auth | Free |

### Recommended (Cost Optimization)

| Variable | Purpose | Savings |
|----------|---------|---------|
| `QWEN_API_KEY` | Cheap simple/medium tasks | 60-70% token savings |
| `KIMI_API_KEY` | Browser agent specialist | Better tool-calling |
| `SUPERMEMORY_API_KEY` | Intelligent user memory | ~$30/mo |

### URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `FRONTEND_URL` | `http://localhost:3000` | Frontend base URL |
| `BACKEND_URL` | `http://localhost:8000` | Backend API base URL |
| `OLLAMA_API_BASE` | `http://localhost:11434` | On-premise LLM endpoint |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY_SALT` | Random per restart | Salt for API key hashing. **SET THIS** for persistence |
| `CORS_ORIGINS` | `FRONTEND_URL` value | Comma-separated allowed origins |
| `MANIFEST_SIGNING_KEY` | Auto-generated | Ed25519 seed for manifest signing |

### Database & Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...@postgres:5432/agentOS` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j connection |
| `SUPERTOKENS_CONNECTION_URI` | `http://supertokens:3567` | Auth service |

## Database Migrations

```bash
# Run pending migrations
make migrate

# Create a new migration after model changes
make migrate-new
```

Migration chain: `001_initial_schema` → `002_add_constraints` → `003_add_stripe_fields`

## Testing

```bash
# Run all backend tests (unit only, no infrastructure needed)
make test-backend

# Run with coverage
make test-cov

# Run specific test file
cd backend && python -m pytest tests/test_e2e.py -v
```

## Monitoring

- **Langfuse dashboard**: `http://langfuse:3001` — LLM traces, costs, latency
- **Health endpoint**: `GET /health` — returns `{"status": "ok"}`
- **Agent health**: `GET /api/v1/agents/health` — per-agent availability
- **Startup warnings**: Check backend logs for ENV warnings on startup

## Billing Plans

| Plan | Price | Tasks/mo | Features |
|------|-------|----------|----------|
| Free | $0 | 5 | Basic tasks, Workhorse model |
| Starter | $29 | 100 | All models, 10 SaaS integrations |
| Pro | $79 | 500 | Everything, voice, API access |
| Team | $199 | 2,000 | RBAC, team API keys |
| Enterprise | $999+ | Unlimited | On-premise, SOC2, SLA |

## Troubleshooting

**API keys not surviving restarts**: Set `API_KEY_SALT` explicitly in `.env`.

**401 on all endpoints**: Check SuperTokens is running and `SUPERTOKENS_CONNECTION_URI` is correct.

**Tasks stuck in "running"**: The backend auto-recovers stuck tasks on startup (re-enqueues them).

**LLM requests failing**: Check `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY` are valid. Review Langfuse traces for details.

**CORS errors in browser**: Update `CORS_ORIGINS` to include your frontend domain.
