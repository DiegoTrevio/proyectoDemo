import secrets

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    kimi_api_key: str = ""
    qwen_api_key: str = ""
    litellm_master_key: str = ""

    # Search & Web
    tavily_api_key: str = ""
    exa_api_key: str = ""
    firecrawl_api_key: str = ""
    perplexity_api_key: str = ""

    # Execution & Sandbox
    e2b_api_key: str = ""
    composio_api_key: str = ""
    steel_api_key: str = ""

    # DeerFlow 2.0
    deerflow_gateway_url: str = "http://deerflow-gateway:8001"
    deerflow_langgraph_url: str = "http://deerflow-langgraph:2024"
    deerflow_enabled: bool = True

    # Hermes Agent (Nous Research) — v0.4.0+
    hermes_enabled: bool = False
    hermes_api_url: str = ""  # HTTP API mode (preferred): e.g. http://hermes:3000
    hermes_cli_path: str = "hermes"  # CLI fallback when api_url is empty
    hermes_model: str = "anthropic/claude-sonnet-4"
    hermes_timeout: int = 300
    hermes_paperclip_enabled: bool = False  # Enable Paperclip adapter bridge

    # Memory — Supermemory (primary L1) + Mem0 (fallback)
    supermemory_api_key: str = ""
    mem0_api_key: str = ""

    # Database
    database_url: str = "postgresql://postgres:postgres@postgres:5432/agentOS"
    redis_url: str = "redis://redis:6379"

    # Neo4j
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3001"

    # Auth
    supertokens_connection_uri: str = "http://supertokens:3567"

    # Media
    elevenlabs_api_key: str = ""
    deepgram_api_key: str = ""

    # Payments
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # URLs (override for production deployments)
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    ollama_api_base: str = "http://localhost:11434"
    litellm_base_url: str = "http://litellm:4000"

    # Security
    manifest_signing_key: str = ""
    api_key_salt: str = ""
    cors_origins: str = ""  # Comma-separated list of allowed origins

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _fill_defaults(self):
        if not self.api_key_salt:
            object.__setattr__(self, "api_key_salt", secrets.token_hex(32))
        if not self.cors_origins:
            object.__setattr__(self, "cors_origins", self.frontend_url)
        return self


settings = Settings()
