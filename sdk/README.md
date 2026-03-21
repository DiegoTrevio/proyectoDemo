# SecureAgent SDK

Enterprise security for AI agents — taint tracking, audit trails, PII detection, approval gates.

## Quick Start

```bash
pip install secureagent
```

```python
from secureagent import SecureAgent

agent = SecureAgent(
    taint_tracking=True,
    pii_detection=True,
    audit_log=True,
    approval_gates={"send_email": "high", "search_web": "low"},
)

# Wrap any tool call with security
result = await agent.secure_call(
    tool_name="search_web",
    tool_fn=my_search_function,
    args={"query": "quarterly revenue"},
    session_id="sess_123",
)

# Detect & redact PII before sending to LLM
clean_text = agent.redact_pii("Contact john@example.com")

# Export tamper-evident audit trail for SOC2/GDPR
trail = agent.export_audit("sess_123")
valid, msg = agent.verify_audit("sess_123")
```

## Features

| Feature | Description |
|---------|-------------|
| **Taint Tracking** | Labels external content and prevents tainted data from triggering destructive actions |
| **PII Detection** | Detects emails, phones, SSNs, credit cards, API keys. Optional Presidio support |
| **Audit Trail** | Merkle-chain audit log — tamper-evident, SOC2/HIPAA/GDPR compliant |
| **Approval Gates** | Blocks HIGH risk actions until human approval via callback |
| **Cloud Dashboard** | Optional: send events to SecureAgent Cloud for visualization |

## Framework Integrations

```python
from secureagent.middleware import secure_tool, SecureToolRegistry

# Decorator approach
@secure_tool(agent, session_id="sess_123")
async def send_email(to: str, body: str):
    ...

# Registry approach
registry = SecureToolRegistry(agent, session_id="sess_123")
registry.register("send_email", send_email_fn)
result = await registry.call("send_email", to="user@example.com", body="Hi")
```

## Cloud Dashboard (Optional)

```python
agent = SecureAgent(
    cloud_api_key="sk-your-key",  # Sends events to dashboard
    ...
)
```

## License

MIT
