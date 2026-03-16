"""Web search tools for AgentOS agents.

Each tool returns a standardized list of results:
  [{"source": str, "content": str, "url": str, "relevance_score": float}]
"""

import logging
from dataclasses import dataclass

import httpx

from config.settings import settings

logger = logging.getLogger("agentos.tools.web_search")


@dataclass
class SearchResult:
    source: str
    content: str
    url: str
    relevance_score: float

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "content": self.content,
            "url": self.url,
            "relevance_score": self.relevance_score,
        }


# ─── Tavily Search ────────────────────────────────────────────────────────

class TavilySearchTool:
    """Web search via Tavily API (default search engine)."""

    def __init__(self):
        self.api_key = settings.tavily_api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("Tavily API key not configured")
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            if resp.status_code != 200:
                logger.error("Tavily search failed: %s", resp.status_code)
                return []

            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append(SearchResult(
                    source="tavily",
                    content=r.get("content", ""),
                    url=r.get("url", ""),
                    relevance_score=r.get("score", 0.5),
                ))
            return results


# ─── Exa Search ───────────────────────────────────────────────────────────

class ExaSearchTool:
    """Semantic deep search via Exa API."""

    def __init__(self):
        self.api_key = settings.exa_api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("Exa API key not configured")
            return []

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": query,
                    "num_results": max_results,
                    "type": "neural",
                    "use_autoprompt": True,
                    "contents": {"text": {"max_characters": 2000}},
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code != 200:
                logger.error("Exa search failed: %s", resp.status_code)
                return []

            data = resp.json()
            results = []
            for r in data.get("results", []):
                text = r.get("text", "")
                if not text and "contents" in r:
                    text = r["contents"].get("text", "")
                results.append(SearchResult(
                    source="exa",
                    content=text,
                    url=r.get("url", ""),
                    relevance_score=r.get("score", 0.5),
                ))
            return results


# ─── Firecrawl ────────────────────────────────────────────────────────────

class FirecrawlTool:
    """Deep web content extraction via Firecrawl API."""

    def __init__(self):
        self.api_key = settings.firecrawl_api_key

    async def extract(self, url: str) -> SearchResult | None:
        """Extract full content from a single URL."""
        if not self.api_key:
            logger.warning("Firecrawl API key not configured")
            return None

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                json={"url": url, "formats": ["markdown"]},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code != 200:
                logger.error("Firecrawl extract failed: %s %s", resp.status_code, url)
                return None

            data = resp.json().get("data", {})
            return SearchResult(
                source="firecrawl",
                content=data.get("markdown", data.get("content", "")),
                url=url,
                relevance_score=1.0,
            )

    async def search(self, query: str, max_results: int = 3) -> list[SearchResult]:
        """Search and extract (uses Tavily for URL discovery, Firecrawl for extraction)."""
        tavily = TavilySearchTool()
        urls = await tavily.search(query, max_results=max_results)
        results = []
        for sr in urls:
            if sr.url:
                extracted = await self.extract(sr.url)
                if extracted:
                    results.append(extracted)
        return results


# ─── Perplexity Sonar ─────────────────────────────────────────────────────

class PerplexitySonarTool:
    """Verified facts with citations via Perplexity Sonar API."""

    def __init__(self):
        self.api_key = settings.perplexity_api_key

    async def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("Perplexity API key not configured")
            return []

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": query}],
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code != 200:
                logger.error("Perplexity search failed: %s", resp.status_code)
                return []

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])

            results = [
                SearchResult(
                    source="perplexity",
                    content=content,
                    url=citations[0] if citations else "",
                    relevance_score=0.95,
                )
            ]
            # Add individual citation results
            for url in citations[1:]:
                results.append(SearchResult(
                    source="perplexity",
                    content="",
                    url=url,
                    relevance_score=0.8,
                ))
            return results
