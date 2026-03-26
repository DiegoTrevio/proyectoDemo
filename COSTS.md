# AgentOS — Cost Analysis

## Quick Summary

| Tier | Monthly Cost | What You Get |
|------|-------------|--------------|
| **Development** | ~$75 | Core agents + cost-first routing (Qwen/Kimi for simple/medium) |
| **Production** | ~$155 | Better search + intelligent memory |
| **Enterprise** | ~$660 | Full capabilities (deep extraction, anti-bot, 150+ SaaS integrations) |

## Required APIs (~$65/month)

| API | Cost | What It Does |
|-----|------|-------------|
| **Anthropic** (Claude Opus + Sonnet) | ~$30/month | Orchestrator brain + complex task execution |
| **Google** (Gemini Flash) | ~$5/month | Fallback workhorse + complex documents (generous free tier) |
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

## Recommended APIs (+$90/month)

| API | Cost | What It Does | Without It |
|-----|------|-------------|------------|
| **Qwen** (DashScope) | ~$5/month | Cost-first routing: simple/medium code, docs, research at $0.0004/1K | Falls back to Gemini ($0.0005/1K) — still works |
| **Kimi** (Moonshot) | ~$5/month | Browser agent specialist: massive tool-calling at $0.0004/1K | Falls back to Claude Sonnet ($0.003/1K) — 7.5x more expensive |
| **Exa** | ~$50/month | Better search for medium+ complexity research | Research quality drops for complex queries |
| **Supermemory** | ~$30/month | Intelligent user memory, profile extraction | Falls back to Mem0 or no L1 memory |
| **Mem0** | Free tier | Fallback memory when Supermemory unavailable | No persistent agent memory |

## Cost-First Routing (with Qwen + Kimi)

AgentOS uses cost-first routing: the cheapest capable model handles each task.
Claude only escalates for complex work.

| Task | Model Used | Cost/1K tokens | vs Claude Sonnet |
|------|-----------|----------------|------------------|
| Code simple | Qwen 3-8B | $0.00008 | **97% cheaper** |
| Code medium | Qwen 3.5+ | $0.0004 | **87% cheaper** |
| Code complex | Claude Sonnet | $0.003 | baseline |
| Browser (all) | Kimi K2.5 | $0.0004 | **87% cheaper** |
| Doc simple | Qwen 3-8B | $0.00008 | **97% cheaper** |
| Doc medium | Qwen 3.5+ | $0.0004 | **87% cheaper** |
| Doc complex | Gemini Flash | $0.0005 | **83% cheaper** |
| Research simple | Qwen 3-8B | $0.00008 | **97% cheaper** |
| Research medium | Qwen 3.5+ | $0.0004 | **87% cheaper** |
| Research complex | Claude Sonnet | $0.003 | baseline |
| Route/Validate | Qwen 3-8B | $0.00008 | **97% cheaper** |
| Orchestrate | Claude Opus | $0.015 | N/A (planning only) |

**Estimated savings: 60-70% on total token costs** for typical workloads
(where ~80% of tasks are simple/medium complexity).

## Optional APIs (+$460/month if all enabled)

| API | Cost | What It Does | Without It |
|-----|------|-------------|------------|
| **Firecrawl** | ~$100/month | Deep content extraction from web pages | Complex research uses only Tavily+Exa |
| **Steel** | ~$100/month | Anti-bot browser sessions, CAPTCHA solving | Browser Agent uses local Playwright (may get blocked) |
| **Composio** | ~$200/month | 150+ SaaS integrations (Gmail, Slack, Notion, etc.) | No SaaS tool access |
| **Stripe** | 2.9% + $0.30/txn | Subscription billing for end users | No payment processing |
| **Perplexity** | ~$20/month | Factual verification with citations | Complex research uses only Tavily+Exa |
| **OpenAI** | Pay-per-use | Additional LLM fallback | Anthropic + Gemini handle everything |

## Cost Optimization Tips

1. **Enable Qwen + Kimi** — $10/month saves 60-70% on token costs
2. **Use Gemini for high-volume tasks** — 10-60x cheaper than Claude for non-critical work
3. **Skip Firecrawl** — Tavily + Exa cover 90% of research needs
4. **Use local Playwright** instead of Steel — free, works for non-protected sites
5. **Skip Composio** until you need SaaS integrations
6. **Cache search results in Redis** — reduces Tavily API calls
7. **Set budget limits per task** — circuit breaker stops at $5 default
8. **Use on-premise Ollama** for internal/testing tasks — completely free
