"""Researcher Agent — searches, analyzes, and synthesizes information.

Routes search complexity:
  - Simple: Tavily only
  - Medium: Tavily + Exa
  - Complex: Tavily + Exa + Firecrawl + Perplexity Sonar

Default model: Gemini 3 Flash (agentOS/workhorse-gemini)
Facts model: Perplexity Sonar (agentOS/facts)
Cheap model: Qwen3.5 Plus (agentOS/workhorse-qwen)
"""

import json
import logging
from datetime import datetime, timezone

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker
from memory.mem0_layer import mem0
from tools.web_search import (
    ExaSearchTool,
    FirecrawlTool,
    PerplexitySonarTool,
    SearchResult,
    TavilySearchTool,
)

logger = logging.getLogger("agentos.agents.researcher")

_SYNTHESIS_PROMPT = """You are a research analyst. Synthesize the following search results into a clear, structured response.

## User Query
{query}

## Search Results
{search_results}

## Prior Knowledge (from memory)
{memory_context}

Respond with JSON only:
{{
  "summary": "comprehensive summary addressing the query",
  "key_facts": ["fact1", "fact2", ...],
  "confidence": 0.0-1.0
}}

Rules:
- Be factual and cite sources where possible
- Include 3-8 key facts
- Set confidence based on source quality and agreement
- If sources conflict, note the disagreement"""


class ResearcherAgent(AbstractAgent):
    """Searches, analyzes, and synthesizes information from multiple sources."""

    name = "researcher"
    task_type = "research"
    default_complexity = "medium"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        super().__init__(circuit_breaker)
        self.tavily = TavilySearchTool()
        self.exa = ExaSearchTool()
        self.firecrawl = FirecrawlTool()
        self.perplexity = PerplexitySonarTool()

    def _determine_complexity(self, goal: str, context: dict) -> str:
        """Infer research complexity from the goal text."""
        complexity = context.get("complexity", "")
        if complexity in ("simple", "medium", "complex"):
            return complexity

        goal_lower = goal.lower()
        complex_signals = ["compare", "analyze", "deep dive", "comprehensive", "detailed",
                           "market", "strategy", "multi", "versus", "pros and cons"]
        simple_signals = ["what is", "define", "who is", "when did", "how many"]

        if any(s in goal_lower for s in complex_signals):
            return "complex"
        elif any(s in goal_lower for s in simple_signals):
            return "simple"
        return "medium"

    async def _search(self, query: str, complexity: str) -> list[SearchResult]:
        """Execute search across tools based on complexity."""
        all_results: list[SearchResult] = []

        # Always use Tavily
        tavily_results = await self.tavily.search(query, max_results=5)
        all_results.extend(tavily_results)

        if complexity in ("medium", "complex"):
            exa_results = await self.exa.search(query, max_results=3)
            all_results.extend(exa_results)

        if complexity == "complex":
            # Deep extraction from top URLs
            top_urls = [r.url for r in tavily_results[:2] if r.url]
            for url in top_urls:
                extracted = await self.firecrawl.extract(url)
                if extracted:
                    all_results.append(extracted)

            # Verified facts via Perplexity
            perplexity_results = await self.perplexity.search(query)
            all_results.extend(perplexity_results)

        return all_results

    def _format_results_for_llm(self, results: list[SearchResult]) -> str:
        """Format search results into a text block for the LLM prompt."""
        if not results:
            return "No search results found."

        sections = []
        for i, r in enumerate(results, 1):
            content_preview = r.content[:1000] if r.content else "(no content)"
            sections.append(
                f"[{i}] Source: {r.source} | URL: {r.url}\n"
                f"    Relevance: {r.relevance_score:.2f}\n"
                f"    Content: {content_preview}"
            )
        return "\n\n".join(sections)

    def _build_sources(self, results: list[SearchResult]) -> list[dict]:
        """Build deduplicated sources list for the output."""
        seen_urls = set()
        sources = []
        for r in results:
            if r.url and r.url not in seen_urls:
                seen_urls.add(r.url)
                sources.append({
                    "url": r.url,
                    "title": r.content[:80].split("\n")[0] if r.content else "",
                    "snippet": r.content[:200] if r.content else "",
                })
        return sources

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Execute research: search → synthesize → store memory."""
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")
        user_id = context.get("user_id", "default")

        complexity = self._determine_complexity(goal, context)
        logger.info("Researcher executing: complexity=%s goal=%s", complexity, goal[:80])

        cb_state = self.cb.new_state()

        # 1. Check memory — "have I researched this before?"
        memory_context = ""
        prior_memories = mem0.search_memory(user_id, goal, limit=3)
        if prior_memories:
            memory_context = "\n".join(f"- {m.content}" for m in prior_memories)
            logger.info("Found %d prior memories for query", len(prior_memories))

        # 2. Search
        try:
            search_results = await self._search(goal, complexity)
        except Exception as e:
            logger.exception("Search failed")
            return AgentResult(
                success=False,
                output="",
                error=f"Search failed: {e}",
            )

        if not search_results:
            return AgentResult(
                success=True,
                output="No search results found for the given query.",
                artifacts=[],
                tokens_used=0,
                cost=0.0,
            )

        # 3. Synthesize with LLM
        formatted_results = self._format_results_for_llm(search_results)
        messages = [
            {"role": "user", "content": _SYNTHESIS_PROMPT.format(
                query=goal,
                search_results=formatted_results,
                memory_context=memory_context or "None",
            )},
        ]

        # Choose model based on complexity
        model_override = None
        if complexity == "simple":
            model_override = "agentOS/workhorse-qwen"
        elif complexity == "complex":
            model_override = "agentOS/workhorse-gemini"
        # medium uses default (workhorse-gemini via model_router)

        try:
            response_text, cb_state = await self.call_llm(
                messages, cb_state, model_override=model_override, max_tokens=4096,
            )
        except Exception as e:
            logger.exception("LLM synthesis failed")
            return AgentResult(
                success=False,
                output="",
                error=f"LLM synthesis failed: {e}",
                tokens_used=cb_state.tokens_used,
                cost=cb_state.total_cost,
            )

        # 4. Parse structured output
        try:
            # Strip markdown code fences if present
            clean = response_text.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                clean = "\n".join(lines)
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            # LLM didn't return valid JSON — use raw text
            parsed = {
                "summary": response_text,
                "key_facts": [],
                "confidence": 0.5,
            }

        summary = parsed.get("summary", response_text)
        key_facts = parsed.get("key_facts", [])
        confidence = parsed.get("confidence", 0.5)
        sources = self._build_sources(search_results)

        # 5. Store findings in Mem0
        if summary and mem0.available:
            mem0.add_memory(
                user_id=user_id,
                content=f"Research on '{goal[:100]}': {summary[:500]}",
                metadata={
                    "task_id": task_id,
                    "type": "research",
                    "sources_count": len(sources),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        output = json.dumps({
            "summary": summary,
            "sources": sources,
            "key_facts": key_facts,
            "confidence": confidence,
        }, indent=2)

        return AgentResult(
            success=True,
            output=output,
            artifacts=[{"type": "research_report", "content": summary}],
            tokens_used=cb_state.tokens_used,
            cost=cb_state.total_cost,
        )
