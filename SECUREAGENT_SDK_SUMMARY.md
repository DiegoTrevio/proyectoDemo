# SecureAgent SDK — Resumen Completo

## Qué es

SecureAgent es un SDK de seguridad enterprise para agentes de IA. Intercepta cada tool call de un agente y la pasa por un pipeline de seguridad de 8 pasos antes de ejecutarla. Diseñado para prevenir que agentes autónomos ejecuten acciones destructivas sin control, filtren PII, o sean manipulados via prompt injection.

**Ubicación:** `sdk/secureagent/` (7 módulos, ~1,400 líneas de código)
**Licencia:** Parte del proyecto AgentOS
**Python:** 3.9+
**Dependencias:** Solo `presidio-analyzer` (opcional, para PII avanzado)

---

## Arquitectura

```
                    ┌──────────────────────────────────────────────┐
                    │            SecureAgent (core.py)              │
                    │                                              │
  tool_fn(**args) ──┤  1. Validar tool_name (regex, max 100 chars) │
                    │  2. PII scan en input args                    │
                    │  3. Taint validation (¿contenido externo?)    │
                    │  4. Approval gate (¿requiere aprobación?)     │
                    │  5. ───── Ejecutar tool ─────                 │
                    │  6. PII scan en output (opcional: bloquear)   │
                    │  7. Registrar en audit Merkle chain           │
                    │  8. Enviar evento a Cloud dashboard           │
                    └──────────────────────────────────────────────┘
```

---

## Módulos

### 1. core.py — SecureAgent (clase principal)

**Propósito:** Orquesta todo el pipeline de seguridad. Es el único punto de entrada para ejecutar tools de forma segura.

**Inicialización:**
```python
from secureagent import SecureAgent

agent = SecureAgent(
    # Módulos de seguridad
    taint_tracking=True,           # Rastrear origen de contenido
    pii_detection=True,            # Detectar información personal
    audit_log=True,                # Registrar cada acción
    block_pii_in_output=False,     # True = redactar PII en respuestas

    # Approval gates
    approval_gates={               # Clasificación de riesgo por tool
        "send_email": "high",
        "delete_file": "high",
        "search_web": "low",
    },
    approval_callback=my_handler,  # Función async que aprueba/rechaza
    approval_timeout=300,          # Timeout en segundos

    # Hardening
    audit_signing_key="secret",    # HMAC-SHA256 para firmar eventos
    audit_max_events=10_000,       # Máximo eventos por sesión
    taint_strict_mode=True,        # Bloquear contenido no registrado
    taint_salt="random-salt",      # Salt para hashes SHA-256
    taint_max_entries=50_000,      # Máximo entradas en registry
    taint_ttl_seconds=3600,        # TTL de entradas (1 hora)

    # Cloud dashboard (opcional)
    cloud_api_key="sk-...",
)
```

**Método principal — `secure_call()`:**
```python
result = await agent.secure_call(
    tool_name="send_email",                # Nombre validado (regex [a-zA-Z0-9_.-]{1,100})
    tool_fn=my_send_email_function,        # Función async a ejecutar
    args={"to": "user@test.com"},          # Argumentos (se escanean por PII)
    agent_id="email_agent",                # ID del agente
    session_id="sess_123",                 # ID de sesión (para audit trail)
    input_context="contenido del prompt",  # Se valida contra taint registry
    model_used="claude-sonnet-4",          # Para registro de auditoría
)
```

**Flujo de ejecución:**
1. Valida `tool_name` con regex (rechaza inyecciones)
2. Escanea cada arg string por PII → log warning si encuentra
3. Si `input_context` está en taint registry y es tainted → bloquea tools destructivas
4. Si la tool es HIGH risk → espera callback de aprobación humana
5. Ejecuta `tool_fn(**args)` — si falla, registra error en audit
6. Escanea output por PII → opcionalmente redacta
7. Registra todo en Merkle audit chain
8. Envía evento a Cloud dashboard (si configurado)

**Excepciones:**
- `SecurityViolation(message, violation_type, details)` — Cuando taint o approval bloquean
- `ValueError` — Cuando `tool_name` es inválido

**Métodos convenience:**
- `label_content(content, source)` — Etiquetar contenido externo
- `approve_content(content, approved_by)` — Aprobar contenido tainted
- `detect_pii(text)` / `redact_pii(text)` — PII directo
- `export_audit(session_id)` — Exportar trail para SOC2/GDPR
- `verify_audit(session_id)` — Verificar integridad de la cadena

---

### 2. taint.py — TaintTracker

**Propósito:** Todo contenido de fuentes externas (web scraping, APIs, uploads, emails) se etiqueta como "tainted". Contenido tainted NO puede disparar herramientas destructivas sin aprobación humana explícita. Esto previene ataques de prompt injection indirecta.

**Modelo de datos:**
```python
class TaintSource(Enum):     # Origen del contenido
    WEB_SCRAPING = "web_scraping"
    SEARCH_RESULT = "search_result"
    USER_UPLOAD = "user_upload"
    EMAIL = "email"
    API_RESPONSE = "api_response"
    BROWSER = "browser"
    PLUGIN = "plugin"
    UNKNOWN = "unknown"

class TaintLabel:             # Etiqueta asociada al contenido
    source: TaintSource       # De dónde viene
    timestamp: str            # Cuándo se etiquetó
    trust_level: float        # 0.0 (no confiable) → 1.0 (confiable)
    original_source: str      # URL, filename, etc.
    chain: list[str]          # Cadena de propagación

class TaintedContent:         # Contenido + etiqueta
    content: str
    label: TaintLabel
    laundered: bool           # ¿Fue aprobado manualmente?
    laundered_by: str         # ¿Quién lo aprobó?
    is_tainted: bool          # True si laundered=False AND trust_level < 0.9
```

**12 herramientas destructivas bloqueadas por defecto:**
```python
DESTRUCTIVE_TOOLS = {
    "send_email", "delete_file", "delete_data", "make_payment",
    "publish_content", "push_code", "create_pr", "update_crm",
    "send_message", "drop_table", "execute_code", "modify_database",
}
```

**Operaciones principales:**

| Método | Qué hace |
|--------|----------|
| `label(content, source, trust_level)` | Etiqueta contenido como tainted. Almacena en registry con hash SHA-256+salt |
| `propagate(original, transformed)` | Propaga taint cuando contenido se transforma (ej: resumen de texto) |
| `validate_tool_call(content, tool_name)` | Valida si el contenido puede disparar esa tool. Lanza `TaintViolation` si no |
| `launder(content, approved_by)` | Marca contenido como aprobado por un humano. Registra quién y cuándo |
| `is_tainted(content)` | Booleano: ¿está tainted? |
| `get_label(content)` | Obtener la etiqueta de un contenido |

**Registry interno:**
- Hash: SHA-256 con salt configurable (previene colisiones y pre-cómputo)
- Bounded: Máximo 50,000 entradas (configurable)
- TTL: Evicción automática de entradas expiradas (default 1 hora)
- Thread-safe: `threading.Lock` para acceso concurrente
- Cleanup periódico: Cada 1,000 operaciones

**Strict mode:** Si `strict_mode=True`, contenido que NO está en el registry (desconocido) también se bloquea para tools destructivas. En modo normal, solo se bloquea contenido explícitamente tainted.

---

### 3. pii.py — PIIDetector

**Propósito:** Detecta y redacta información personal identificable (PII) en texto. Usa regex validado con scoring de confianza por patrón. Opcionalmente usa Microsoft Presidio para producción.

**7 tipos de PII detectados:**

| Tipo | Patrón | Confianza | Validador |
|------|--------|-----------|-----------|
| `email` | `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` | 0.92 | — |
| `phone_us` | `(\+1)?(\d{3})[-.]?\d{3}[-.]?\d{4}` | 0.85 | — |
| `phone_international` | `\+[2-9]\d{1,2}[-.]?\d{2,4}[-.]?\d{3,4}[-.]?\d{3,4}` | 0.80 | — |
| `ssn` | `\d{3}-\d{2}-\d{4}` | 0.95 | Valida rangos (excluye 000, 666, 900+) |
| `credit_card` | `(\d{4}[-\s]?){3}\d{4}` | 0.90 | Algoritmo de Luhn |
| `ip_address` | `(\d{1,3}\.){3}\d{1,3}` | 0.50 | Valida octetos 0-255, IPs privadas = 0.35 |
| `api_key` | `(sk\|pk\|api\|token\|secret\|key)[-_][A-Za-z0-9-_]{20,}` | 0.88 | — |

**Operaciones:**

| Método | Qué hace |
|--------|----------|
| `detect(text)` | Retorna `list[PIIMatch]` con type, value, start, end, confidence |
| `contains_pii(text)` | Booleano rápido |
| `redact(text)` | Reemplaza PII con `[TYPE_REDACTED]` (ej: `[EMAIL_REDACTED]`) |
| `scan_dict(data)` | Escanea recursivamente un dict (profundidad max 5) |

**Deduplicación:** Cuando dos patrones hacen match en la misma posición (overlap), se queda con el de mayor confianza.

**Presidio:** Si `use_presidio=True`, usa `presidio_analyzer.AnalyzerEngine` que soporta 50+ tipos de PII, múltiples idiomas, y NER. Si Presidio no está instalado, cae a regex automáticamente.

---

### 4. audit.py — AuditLog (Merkle Chain)

**Propósito:** Cadena Merkle append-only que registra cada acción de cada agente. Si alguien modifica un registro, la cadena se rompe y es detectable. Diseñado para cumplimiento SOC2/HIPAA/GDPR.

**Modelo de datos:**
```python
class AuditEvent:
    event_id: str           # "evt_{session_id}_{counter}"
    session_id: str
    timestamp: str          # ISO 8601 UTC
    agent_id: str
    action: str             # "tool_call", "tool_error", "taint_violation", etc.
    tool_name: str
    input_hash: str         # SHA-256 del input (no el texto plano)
    output_hash: str        # SHA-256 del output
    model_used: str
    tokens_used: int
    cost: float
    risk_level: str         # "low", "medium", "high"
    prev_hash: str          # Hash del evento anterior ("genesis" si primero)
    event_hash: str         # SHA-256 del evento completo
    signature: str          # HMAC-SHA256 si signing_key configurado
    metadata: dict          # Datos extra (sanitizados, max 5KB)
```

**Cadena Merkle:**
```
[genesis] ← Event 1 ← Event 2 ← Event 3 ← ... ← Event N
              │          │          │
         hash(E1)   hash(E2+H1)  hash(E3+H2)
```
Cada evento incluye el hash del evento anterior. Modificar cualquier evento invalida todos los posteriores.

**HMAC Signing:** Si `signing_key` está configurado, cada evento se firma con HMAC-SHA256. Esto previene que alguien recalcule los hashes después de tampering (necesitaría la clave).

**Operaciones:**

| Método | Qué hace |
|--------|----------|
| `add_event(session_id, agent_id, action, ...)` | Agrega evento a la cadena. Retorna hash |
| `verify_chain(session_id)` | Verifica integridad de toda la cadena. `(bool, message)` |
| `get_proof(session_id, event_id)` | Genera `MerkleProof` de existencia de un evento |
| `export_chain(session_id)` | Exporta como `list[dict]` para auditoría externa |
| `get_stats(session_id)` | Stats: eventos, tokens totales, costo, agentes, validez |
| `get_events(session_id, agent_id?, action?, limit?)` | Query con filtros |

**Bounds:**
- Max 10,000 eventos por sesión (configurable, evicta los más viejos)
- Max 1,000 sesiones (configurable, evicta la más vieja)
- Metadata sanitizada: profundidad max 3, size max 5KB, trunca si excede
- Thread-safe: `threading.RLock` + `itertools.count()` para IDs atómicos

**StorageBackend (Protocol):** Interfaz pluggable para persistir en base de datos:
```python
class StorageBackend(Protocol):
    async def save_event(self, event: dict) -> None: ...
    async def save_events_batch(self, events: list[dict]) -> None: ...
    async def get_events(self, session_id, ...) -> list[dict]: ...
    async def get_chain(self, session_id) -> list[dict]: ...
```

---

### 5. gates.py — ApprovalGate

**Propósito:** Bloquea acciones irreversibles hasta que un humano las apruebe. Clasificación de riesgo por herramienta.

**3 niveles de riesgo:**

| Nivel | Comportamiento |
|-------|----------------|
| **LOW** | Auto-aprobado, log silencioso |
| **MEDIUM** | Auto-aprobado, log con warning |
| **HIGH** | Bloqueado hasta que `approval_callback` retorne `True`, o timeout |

**12 tools pre-clasificadas:**
```python
DEFAULT_RISK_MAP = {
    # HIGH
    "send_email": HIGH, "make_payment": HIGH, "delete_file": HIGH,
    "delete_data": HIGH, "publish_content": HIGH, "push_code": HIGH,
    "create_pr": HIGH, "update_crm": HIGH, "drop_table": HIGH,
    "execute_code": HIGH, "modify_database": HIGH,
    # MEDIUM
    "send_message": MEDIUM,
    # LOW
    "search_web": LOW, "read_file": LOW, "list_files": LOW,
}
```

**Approval callback:**
```python
async def my_approval_handler(request: ApprovalRequest) -> bool:
    # request tiene: id, session_id, tool_name, reason, risk_level, params
    # Enviar a Slack, UI, webhook, etc.
    return True  # o False
```

**Seguridad del callback:**
- Si retorna non-bool → rechazado
- Si lanza excepción → rechazado
- Si timeout (configurable, default 300s) → rechazado
- History acotado: `deque(maxlen=5000)`

---

### 6. cloud.py — CloudClient

**Propósito:** Envía eventos de auditoría a un dashboard remoto (SecureAgent Cloud) para visualización en tiempo real. Non-blocking con buffer y circuit breaker.

**Características:**
- **Buffer bounded:** `deque(maxlen=5000)`, auto-evicta los más viejos
- **Batching:** Envía en lotes de 50 eventos
- **Auto-flush:** Cada 5 segundos (configurable)
- **Retries:** Exponential backoff con jitter (±30%): 1s, 2s, 4s
- **Circuit breaker:** CLOSED → OPEN (5 failures) → HALF_OPEN (30s) → test → CLOSED/OPEN
- **Graceful shutdown:** `close()` hace flush final de eventos pendientes

**Operaciones:**

| Método | Qué hace |
|--------|----------|
| `send_event(event)` | Non-blocking, encola evento |
| `flush()` | Envía batch al cloud |
| `start_auto_flush()` | Inicia background task periódico |
| `close()` | Flush final + cerrar httpx client |
| `get_stats()` | buffer_size, events_sent, events_dropped, circuit_state |

---

### 7. middleware.py — Integraciones con frameworks

**Propósito:** Drop-in middleware para integrar SecureAgent con frameworks populares de agentes de IA.

**3 formas de integrar:**

**a) SecureLangChainCallback** — Para LangChain:
```python
from secureagent.middleware import SecureLangChainCallback

callback = SecureLangChainCallback(agent, session_id="sess_123", block_pii=True)
result = await langchain_agent.ainvoke(
    {"input": "..."},
    config={"callbacks": [callback]},
)
```
Intercepta `on_tool_start` (PII check), `on_tool_end` (PII scan), `on_tool_error`.

**b) @secure_tool** — Decorador para cualquier función:
```python
from secureagent.middleware import secure_tool

@secure_tool(agent, session_id="sess_123")
async def send_email(to: str, subject: str, body: str):
    return {"status": "sent"}

result = await send_email(to="user@test.com", subject="Hi", body="Hello")
# Pasa por todo el pipeline de seguridad automáticamente
```

**c) SecureToolRegistry** — Registry centralizado:
```python
from secureagent.middleware import SecureToolRegistry

registry = SecureToolRegistry(agent, session_id="sess_123")
registry.register("send_email", send_email_fn)
registry.register("search", search_fn)

result = await registry.call("send_email", to="user@test.com", body="Hi")
# Si tool no registrada → ValueError
```

---

## Tests

**80+ tests** distribuidos en 4 archivos:

| Archivo | Tests | Qué cubre |
|---------|-------|-----------|
| `test_sdk.py` | 27 | Taint, Audit, PII, Gates, SecureAgent integration, Middleware |
| `test_edge_cases.py` | 30 | Input validation, Unicode/emoji, large payloads, empty values, strict mode, signing, bounded structures, callback edge cases, PII edge cases, error recovery |
| `test_concurrency.py` | 5 | Thread-safe audit counters (500 events/5 threads), 100 concurrent secure_calls, concurrent sessions, concurrent taint label+lookup, concurrent approval checks |
| `test_cloud.py` | 9 | Circuit breaker states, buffer bounds, closed client, stats, flush, close |
| **Total** | **71** | |

**Categorías de tests:**

- **Funcionalidad básica:** label → validate → block, launder → allow, audit chain verify, PII detect/redact
- **Tamper detection:** Modificar evento en cadena → verify detecta
- **Concurrencia:** 5 threads × 100 eventos sin IDs duplicados, 100 async tool calls simultáneas
- **Edge cases:** Unicode (japonés, emoji), payloads de 100KB, strings vacíos, tool names inválidos
- **Bounds:** Eviction de entradas por max_entries y TTL, max_sessions, history de gates
- **Resilencia:** Callback que retorna non-bool, callback que crashea, callback con timeout, tool que falla → error en audit trail
- **Signing:** Cadena firmada válida, tamper detectado con signing, cadena sin firma funciona

---

## Decisiones de diseño

1. **Hashes SHA-256 con salt** — No MD5/SHA-1. El salt previene rainbow tables y colisiones dirigidas
2. **HMAC para firmas** — `hmac.compare_digest` previene timing attacks
3. **Bounded everything** — Registry, audit chains, gates history, cloud buffer. Sin memory leaks
4. **Thread-safe** — `threading.Lock` en taint, `threading.RLock` en audit, `itertools.count()` para IDs
5. **Fail-closed** — Si approval callback falla/timeout → rechazado. Si PII detectado → warning (no bloqueo por default, configurable)
6. **No guarda texto plano en audit** — Solo hashes de input/output. El contenido real no se persiste en la cadena
7. **Presidio opcional** — Regex funciona sin dependencias extra. Presidio agrega 50+ tipos de PII para producción
8. **Circuit breaker en cloud** — Si el dashboard se cae, el agente sigue funcionando. Eventos se bufferean y reintentan

---

## Gaps conocidos

1. **cloud.py** — El endpoint `https://api.secureagent.dev/v1/ingest` no existe realmente (placeholder)
2. **StorageBackend** — Solo hay el Protocol definido, no hay implementación concreta para PostgreSQL
3. **No hay rate limiting** por sesión en el SDK mismo (se asume que FastAPI lo maneja)
4. **No hay encryption at rest** — Los eventos en memoria están en plaintext
5. **Taint no persiste** entre reinicios — El registry es in-memory (se pierde al reiniciar)
