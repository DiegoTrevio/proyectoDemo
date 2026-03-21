.PHONY: help up down logs test lint dev-setup health migrate shell

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ─── Docker ───────────────────────────────────────────────────────────
up: ## Start all services
	docker compose up -d

up-full: ## Start all services including frontend
	docker compose --profile with-frontend up -d

down: ## Stop all services
	docker compose down

logs: ## Tail logs for all services
	docker compose logs -f --tail=50

logs-backend: ## Tail backend logs
	docker compose logs -f --tail=100 backend

rebuild: ## Rebuild and restart all services
	docker compose up -d --build

# ─── Development ──────────────────────────────────────────────────────
dev-setup: ## Bootstrap local development environment
	./scripts/dev-setup.sh

dev: ## Run backend in development mode (local, no Docker)
	cd backend && uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run frontend in development mode
	cd frontend && npm run dev

# ─── Database ─────────────────────────────────────────────────────────
migrate: ## Run Alembic migrations
	cd backend && alembic upgrade head

migrate-new: ## Create a new migration (usage: make migrate-new msg="add users table")
	cd backend && alembic revision --autogenerate -m "$(msg)"

# ─── Testing ──────────────────────────────────────────────────────────
test: ## Run all tests
	./scripts/run-tests.sh

test-backend: ## Run backend tests only
	cd backend && python -m pytest tests/ -v --tb=short

test-sdk: ## Run SDK tests only
	cd sdk && python -m pytest tests/ -v --tb=short

test-cov: ## Run backend tests with coverage
	cd backend && python -m pytest tests/ -v --tb=short --cov=. --cov-report=term-missing

# ─── Quality ──────────────────────────────────────────────────────────
lint: ## Lint frontend
	cd frontend && npm run lint

# ─── Operations ───────────────────────────────────────────────────────
health: ## Check health of all services
	./scripts/health-check.sh

shell: ## Open a shell in the backend container
	docker compose exec backend bash

psql: ## Connect to PostgreSQL
	docker compose exec postgres psql -U postgres -d agentOS

redis-cli: ## Connect to Redis
	docker compose exec redis redis-cli
