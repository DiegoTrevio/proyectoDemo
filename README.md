# AgentOS

Plataforma de agentes de IA autónomos. Stack basado en DeerFlow 2.0, LangGraph, Claude y routing multi-modelo via LiteLLM.

## Requisitos

- Docker & Docker Compose v2+
- API keys para los servicios configurados

## Setup rápido

```bash
# 1. Copiar variables de entorno
cp .env.example .env

# 2. Llenar las API keys en .env (mínimo ANTHROPIC_API_KEY)

# 3. Levantar todos los servicios
docker compose up -d

# 4. Verificar que el backend responde
curl http://localhost:8000/health
# => {"status": "ok"}

# 5. Ver el estado de todos los servicios
docker compose ps
```

## Servicios

| Servicio     | Puerto | Descripción                     |
|-------------|--------|---------------------------------|
| backend     | 8000   | FastAPI + uvicorn               |
| frontend    | 3000   | Next.js 14 (perfil `with-frontend`) |
| litellm     | 4000   | Router multi-modelo LLM        |
| redis       | 6379   | Cache y message broker          |
| postgres    | 5432   | PostgreSQL 16 + pgvector        |
| neo4j       | 7474/7687 | Base de datos de grafos      |
| langfuse    | 3001   | Observabilidad LLM             |
| llm-guard   | 8080   | Seguridad de prompts/outputs   |
| letta       | 8283   | Servidor de memoria            |
| supertokens | 3567   | Autenticación                  |

## Desarrollo

Para desarrollo con hot-reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

## Estructura del proyecto

```
agentOS/
├── backend/
│   ├── agents/        # Definición de agentes
│   ├── tools/         # Herramientas de agentes
│   ├── memory/        # Integración de memoria
│   ├── security/      # LLM Guard y NeMo Guardrails
│   ├── api/routes/    # Endpoints FastAPI
│   ├── config/        # Configuración y settings
│   └── agency/        # Orquestación de agentes
├── frontend/          # Next.js 14 + CopilotKit
├── mcp-servers/       # Servidores FastMCP
├── docker-compose.yml
└── docker-compose.dev.yml
```
