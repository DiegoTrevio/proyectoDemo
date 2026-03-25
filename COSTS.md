# AgentOS — Cost Analysis

## Quick Summary

| Tier | Monthly Cost | What You Get |
|------|-------------|--------------|
| **Development** | ~$60 | Core agents working (research, code, browser, documents) |
| **Production** | ~$100 | Better search + intelligent memory |
| **Enterprise** | ~$660 | Full capabilities (deep extraction, anti-bot, 150+ SaaS integrations) |

## Required APIs (~$60/month)

| API | Cost | What It Does |
|-----|------|-------------|
| **Anthropic** (Claude Opus + Sonnet) | ~$30/month | Orchestrator brain + workhorse agent execution |
| **Google** (Gemini Flash) | ~$5/month | Cheap workhorse fallback + fast/cheap tier (generous free tier) |
| **Tavily** | ~$20/month | Web search for all research complexity levels |
| **E2B** | ~$10/month | Sandboxed code execution for Coder Agent |

## Self-Hosted Services (Free)

These run in Docker Compose — no external API cost:

| Service | Purpose |
|---------|---------|
| PostgreSQL + pgvector | Database + vector embeddings |
| Redis | Cache, PubSub, session store |
| Neo4j | Knowledge graph (Graphiti temporal facts) |
| LiteLLM | LLM router with fallbacks and cost tracking |
| SuperTokens | Authentication (email+password, OAuth) |
| DeerFlow 2.0 | Agent orchestration runtime (LangGraph) |
| Langfuse | LLM observability and tracing |
| LLM Guard | Prompt/output security scanning |
| Letta | Memory server |

## Recommended APIs (+$50-80/month)

| API | Cost | What It Does | Without It |
|-----|------|-------------|------------|
| **Exa** | ~$50/month | Better search for medium+ complexity research | Research quality drops for complex queries |
| **Supermemory** | ~$30/month | Intelligent user memory, profile extraction | Falls back to Mem0 or no L1 memory |
| **Mem0** | Free tier | Fallback memory when Supermemory unavailable | No persistent agent memory |

## Optional APIs (+$460/month if all enabled)

| API | Cost | What It Does | Without It |
|-----|------|-------------|------------|
| **Firecrawl** | ~$100/month | Deep content extraction from web pages | Complex research uses only Tavily+Exa |
| **Steel** | ~$100/month | Anti-bot browser sessions, CAPTCHA solving | Browser Agent uses local Playwright (may get blocked) |
| **Composio** | ~$200/month | 150+ SaaS integrations (Gmail, Slack, Notion, etc.) | No SaaS tool access |
| **Stripe** | 2.9% + $0.30/txn | Subscription billing for end users | No payment processing |
| **Perplexity** | ~$20/month | Factual verification with citations | Complex research uses only Tavily+Exa |
| **OpenAI** | Pay-per-use | Additional LLM fallback | Anthropic + Gemini handle everything |
| **Qwen** | ~$5/month | Cheap Chinese LLM for cost optimization | Gemini Flash handles cheap tier |
| **Kimi** | ~$5/month | Moonshot LLM for browser agent tool calling | Sonnet/Gemini handle browser tasks |

## Cost Optimization Tips

1. **Use Gemini for high-volume tasks** — 10-60x cheaper than Claude for non-critical work
2. **Skip Firecrawl** — Tavily + Exa cover 90% of research needs
3. **Use local Playwright** instead of Steel — free, works for non-protected sites
4. **Skip Composio** until you need SaaS integrations
5. **Cache search results in Redis** — reduces Tavily API calls
6. **Set budget limits per task** — circuit breaker stops at $5 default
7. **Use on-premise Ollama** for internal/testing tasks — completely free
