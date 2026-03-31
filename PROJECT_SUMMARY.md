# AgentOS — Resumen Completo del Proyecto

## Qué es

AgentOS es una plataforma autónoma de agentes de IA con seguridad enterprise-grade. Combina orquestación multi-agente (LangGraph), sistema de memoria de 5 capas, 12+ servicios Docker, y un SDK de seguridad propio (SecureAgent) con taint tracking, auditoría Merkle, detección de PII, y approval gates.

---

## Arquitectura General

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js 14)                     │
│  React 18 · CopilotKit · Tailwind · Framer Motion · XYFlow │
│                      Puerto :3000                           │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST / WebSocket / SSE
┌──────────────────────────▼──────────────────────────────────┐
│                   Backend (FastAPI)                          │
│  Orchestrator · 6 Agentes · Memory Manager · Policy Engine  │
│               Puerto :8000 · Python 3.12                    │
├─────────────────────────────────────────────────────────────┤
│  Middleware: Rate Limiter · CORS · Security Headers         │
│  Headers: X-Request-ID · HSTS · X-Frame-Options · CSP      │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────┘
   │      │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
 Redis  Postgres Neo4j LiteLLM Langfuse LLM   Super  DeerFlow
 :6379  :5432   :7687  :4000   :3001  Guard  Tokens  :2024/:8001
                                      :8080  :3567
```

---

## Servicios Docker (docker-compose.yml)

| Servicio | Imagen/Build | Puerto | Función |
|----------|-------------|--------|---------|
| **backend** | Dockerfile.backend (multi-stage) | 8000 | FastAPI, agentes, API |
| **frontend** | Dockerfile.frontend | 3000 | Next.js 14, UI enterprise |
| **litellm** | ghcr.io/berriai/litellm | 4000 | Router multi-LLM (Anthropic, OpenAI, Google, Qwen, Kimi, Perplexity) |
| **redis** | redis:7-alpine | 6379 | Cache, rate limiting, sesiones (512MB, LRU, AOF) |
| **postgres** | pgvector/pgvector:pg16 | 5432 | Base de datos + embeddings vectoriales |
| **neo4j** | neo4j:5-community | 7474/7687 | Grafo de conocimiento (APOC plugins) |
| **langfuse** | langfuse/langfuse | 3001 | Observabilidad/tracing de LLMs |
| **llm-guard** | Dockerfile.llm-guard | 8080 | Filtrado de contenido, seguridad |
| **letta** | ghcr.io/letta-ai/letta | 8283 | Servidor de memoria |
| **supertokens** | supertokens-postgresql | 3567 | Autenticación |
| **deerflow-langgraph** | ghcr.io/bytedance/deer-flow | 2024 | Runtime de agentes (LangGraph) |
| **deerflow-gateway** | ghcr.io/bytedance/deer-flow-gateway | 8001 | Gateway API (skills, files) |
| **hermes** | nousresearch/hermes-agent:v0.5.0 | — | Hermes Agent (Nous Research) — 40+ tools, multi-plataforma, Paperclip bridge para task management |

Variantes adicionales:
- `docker-compose.prod.yml`: JSON logging, resource limits, restart policies
- `docker-compose.test.yml`: Entorno de tests aislado

---

## Sistema de Agentes

### Orquestador (LangGraph State Machine)
El orquestador (`backend/agents/orchestrator.py`) coordina todos los agentes usando un grafo de estados LangGraph. Decide qué agente usar basado en el tipo de tarea.

### Agentes implementados

| Agente | Archivo | Función |
|--------|---------|---------|
| **Orchestrator** | `agents/orchestrator.py` | Máquina de estados LangGraph, coordina agentes |
| **Researcher** | `agents/researcher.py` | Búsqueda multi-fuente (Tavily, Exa, Firecrawl) + integración con memoria |
| **Coder** | `agents/coder.py` | Ejecución de código en sandbox E2B |
| **Browser** | `agents/browser.py` | Navegación web con Steel sessions + browser-use |
| **Document** | `agents/document.py` | Generación de archivos (PPTX, DOCX, PDF, XLSX), imágenes con Gemini, parsing con Docling |
| **DeerFlow** | `agents/deerflow.py` | SuperAgent enterprise (ByteDance), ejecución via LangGraph Server |
| **Hermes** | `agents/hermes.py` | Nous Research Hermes Agent v0.5.0 — 40+ tools, MCP client, plugin hooks, Paperclip bridge para task management, wraps CLI binario |

Componentes auxiliares:
- `agents/dispatcher.py` — Despacha tareas al agente correcto
- `agents/base_agent.py` — Clase base abstracta
- `agents/circuit_breaker.py` — Circuit breaker para resiliencia
- `agents/validator.py` — Validación de outputs

---

## Sistema de Memoria (5 capas)

```
┌─────────────────────────────────────────────────┐
│           Memory Manager (manager.py)            │
│  gather_context() → pre-ejecución               │
│  save_learnings() → post-ejecución               │
├─────────────────────────────────────────────────┤
│                                                  │
│  L0: OpenViking        — Context rápido local    │
│      openviking_layer.py  (~100 tokens, <10ms)   │
│                                                  │
│  L1: Supermemory (PRIMARY) — Preferencias +      │
│      supermemory_layer.py    historial usuario    │
│      ↳ Fallback: Mem0        Búsqueda híbrida    │
│        mem0_layer.py         (RAG + memory)      │
│                                                  │
│  L2: Graphiti/Neo4j    — Hechos con timestamp    │
│      graphiti_layer.py    en grafo de conocimiento│
│                                                  │
│  L3: Redis             — Cache de sesión         │
│      redis_session.py     Estado de tareas       │
│                                                  │
│  L4: Supermemory Profile — Perfil de usuario     │
│      supermemory_layer.py   Hechos estáticos +   │
│                             contexto dinámico    │
│                             (~50ms)              │
└─────────────────────────────────────────────────┘
```

**Supermemory** reemplaza Mem0 como proveedor principal:
- #1 en benchmarks LongMemEval, LoCoMo, ConvoMem
- Auto-extracción de hechos, resolución de contradicciones
- Auto-forgetting temporal
- Conectores: Google Drive, Gmail, Notion, GitHub
- Multimodal: PDF, imágenes/OCR, video, código/AST
- Mem0 se mantiene como fallback graceful

---

## SDK SecureAgent — Seguridad Enterprise

### Componentes del SDK (`sdk/secureagent/`)

```
SecureAgent (core.py)
  │
  ├── TaintTracker (taint.py)
  │   ├── SHA-256 con salt configurable
  │   ├── Strict mode: bloquea contenido desconocido
  │   ├── Registry con TTL y eviction automática (50K entries, 1h TTL)
  │   ├── Propagación de taint en transformaciones
  │   ├── "Laundering" con trail de auditoría
  │   └── 12 herramientas destructivas bloqueadas por defecto:
  │       send_email, delete_file, make_payment, push_code,
  │       create_pr, execute_code, modify_database, etc.
  │
  ├── PIIDetector (pii.py)
  │   ├── 7 tipos de PII: email, phone_us, phone_intl, SSN, credit_card, IP, API key
  │   ├── Validadores: Luhn (tarjetas), octetos IP, rangos SSN
  │   ├── Scoring de confianza por patrón (0.35-0.95)
  │   ├── Redacción automática con deduplicación de overlaps
  │   ├── Soporte Presidio opcional (producción)
  │   └── Scan recursivo de dicts (profundidad 5)
  │
  ├── AuditLog (audit.py) — Merkle Chain
  │   ├── Cadena Merkle append-only, tamper-evident
  │   ├── HMAC-SHA256 signing (previene re-cómputo de hashes)
  │   ├── Thread-safe con RLock + counter atómico
  │   ├── Bounded chains (10K eventos/sesión, 1K sesiones)
  │   ├── MerkleProof para verificar existencia de eventos
  │   ├── Export para SOC2/HIPAA/GDPR
  │   └── StorageBackend pluggable (Protocol)
  │
  ├── ApprovalGate (gates.py)
  │   ├── 3 niveles de riesgo: LOW (auto-pass), MEDIUM (log+pass), HIGH (requiere aprobación)
  │   ├── Callback async con timeout configurable (default 300s)
  │   ├── 12 tools pre-clasificados por riesgo
  │   ├── History acotado (deque, default 5K)
  │   └── Risk map extensible en runtime
  │
  ├── CloudClient (cloud.py) — Dashboard remoto (stub)
  │
  └── Middleware (middleware.py)
      ├── SecureLangChainCallback — callback para LangChain
      ├── @secure_tool — decorador para cualquier función async
      └── SecureToolRegistry — registry con seguridad
```

### Pipeline de Seguridad (SecureAgent.secure_call)

```
Input → Validate tool_name → PII scan input → Taint validation →
  Approval gate → Execute tool → PII scan output → Audit log →
  Cloud event → Output
```

### Seguridad Backend Adicional

| Componente | Archivo | Función |
|------------|---------|---------|
| **Policy Engine** | `security/policy_engine.py` | Políticas por cliente desde PostgreSQL (acciones permitidas, topics bloqueados, costos máximos, approval requirements) |
| **NeMo Guardrails** | `security/guardrails.py` | Guardrails de NVIDIA para LLMs |
| **LLM Guard** | Docker service :8080 | Filtrado de contenido a nivel de pipeline |
| **Auth** | `integrations/auth.py` | SuperTokens + verificación de manifiestos (Ed25519) |
| **API Keys** | `api/routes/api_keys.py` | Gestión de API keys con hash+salt |
| **Security Headers** | `api/main.py` | HSTS, X-Frame-Options, X-XSS-Protection, CSP, Referrer-Policy |
| **Rate Limiter** | `api/middleware/rate_limiter.py` | Rate limiting por IP/API key via Redis |

---

## API REST (FastAPI)

### Endpoints registrados

| Router | Prefijo | Función |
|--------|---------|---------|
| `tasks` | `/api/v1/tasks` | CRUD de tareas, ejecución |
| `stream` | `/api/v1/stream` | SSE streaming de resultados |
| `agents` | `/api/v1/agents` | Gestión de agentes |
| `billing` | `/api/v1/billing` | Stripe integration |
| `memory` | `/api/v1/memory` | Búsqueda y gestión de memoria |
| `ingest` | `/api/v1/ingest` | Ingestión de documentos |
| `dashboard` | `/api/v1/dashboard` | Stats y métricas |
| `api_keys` | `/api/v1/keys` | Gestión de API keys |
| `websocket` | `/ws` | WebSocket para real-time |

### Health check
```
GET /health → {"status": "ok"}
```

---

## MCP Servers (Model Context Protocol)

3 servidores FastMCP para exponer capabilities a LLMs:

| Server | Archivo | Tools |
|--------|---------|-------|
| **Memory** | `mcp-servers/memory_server.py` | `search_memory`, `add_memory`, `get_user_profile`, `get_user_preferences` |
| **Knowledge** | `mcp-servers/knowledge_server.py` | Acceso a base de conocimiento |
| **Tools** | `mcp-servers/tools_server.py` | Descubrimiento y ejecución de herramientas |

---

## Integraciones

| Integración | Archivo | Estado |
|-------------|---------|--------|
| **Stripe Billing** | `integrations/stripe_billing.py` | Completo (webhooks, suscripciones) |
| **Billing Middleware** | `integrations/billing_middleware.py` | Completo (control de uso) |
| **Auth (SuperTokens)** | `integrations/auth.py` | Completo (verificación de manifiestos Ed25519) |
| **OpenClaw** | `integrations/openclaw_bridge.py` | Código existe, router NO registrado en main.py |
| **Composio** | via `composio-core` | Disponible como dependencia |

---

## Frontend (Next.js 14)

- **Framework**: Next.js 14 + React 18
- **UI**: Enterprise dark theme, drag-and-drop flow builder (@xyflow/react)
- **Copilot**: CopilotKit integration
- **Styling**: Tailwind CSS + Framer Motion
- **Profiles**: Solo se inicia con `docker compose --profile with-frontend up`

---

## CI/CD (.github/workflows/ci.yml)

```yaml
Triggers: push to main/develop, PRs to main
Jobs:
  1. sdk-tests     → pytest sdk/
  2. backend-tests → pytest backend/ (PostgreSQL + Redis services)
  3. frontend-lint → npm run lint
  4. docker-build  → Builds backend + frontend images (on success)
```

---

## Dependencias principales (requirements.txt)

| Categoría | Paquetes |
|-----------|----------|
| **Web** | FastAPI 0.115, Uvicorn 0.34, httpx 0.28 |
| **LLM** | LangChain 0.3, LangGraph 0.2, LiteLLM 1.55, langchain-openai 0.3 |
| **DB** | SQLAlchemy 2.0 (async), asyncpg, aiosqlite, Alembic 1.14 |
| **Memoria** | mem0ai 0.1.42, graphiti-core 0.5 |
| **Búsqueda** | tavily-python, exa-py, firecrawl-py |
| **Ejecución** | e2b-code-interpreter 1.0, browser-use 0.1, playwright 1.49 |
| **Documentos** | python-pptx, python-docx, reportlab, openpyxl, docling 2.14 |
| **Seguridad** | nemoguardrails 0.11, llm-guard 0.3, presidio-analyzer 2.2, presidio-anonymizer 2.2, cryptography 44.0 |
| **Pagos/Auth** | stripe 11.4, supertokens-python 0.25 |
| **Observability** | langfuse 2.57 |
| **MCP** | fastmcp 2.3 |
| **LLM (Google)** | google-genai 1.7 |
| **Agentes externos** | Hermes Agent v0.5.0 (Nous Research) — 40+ tools, MCP client, plugin architecture, Paperclip bridge (hermes-paperclip-adapter) |
| **Missing** | ⚠️ `supermemory` NO está en requirements.txt |

---

## Tests

| Archivo | Tests | Cobertura |
|---------|-------|-----------|
| `tests/test_sdk_api.py` | 29 | SecureAgent SDK completo |
| `tests/test_supermemory.py` | 23 | Supermemory layer + manager + MCP |
| `tests/test_hermes.py` | 19 | Hermes Agent + CLI wrapper |
| **Total** | **71** | Todos passing |

---

## Historial de commits (branch)

```
5e4de0a feat: Orchestrator Agent (LangGraph state machine)
7036385 feat: Researcher Agent (multi-source search + Mem0)
8bed119 feat: Coder Agent (E2B sandbox)
2514c17 feat: Browser Agent (Steel + browser-use)
d6ff00b feat: Document Agent (file gen, Gemini, Docling)
01254de feat: Security layer (NeMo, LLM Guard, Policy Engine)
6987e2f feat: Frontend Next.js 14 (dark enterprise UI)
e31760d feat: 4-layer memory (OpenViking, Mem0, Graphiti, Redis)
7cb80cb feat: Final integrations (8-layer security, Composio, billing, auth, MCP)
86ca05f feat: SecureAgent SDK (taint, audit, PII, gates)
9791451 feat: Robustness (migrations, tests, DevOps)
8ccd72b feat: Production security + auth hardening
c8def56 feat: DeerFlow 2.0 SuperAgent integration
867fc4e fix: Auth hash mismatch + production hardening
44a7c37 feat: Production infrastructure (Docker multi-stage, CI/CD, JSON logging)
1349c3c feat: Hermes Agent (Nous Research, 30+ tools, 80+ skills)
414447d feat: Supermemory as primary L1 memory (replaces Mem0)
```

---

## Gaps conocidos

1. **`supermemory` no está en requirements.txt** — Falla en runtime al importar
2. **OpenClaw router no registrado** en main.py — El endpoint no está accesible
3. **WebSocket handlers vacíos** — Algunos `pass` stubs
4. **SDK cloud.py** — Tiene `raise NotImplementedError` en métodos clave
5. **Frontend no conectado** por defecto al backend (requiere profile)
