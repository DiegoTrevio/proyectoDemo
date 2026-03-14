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

    # Memory
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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
