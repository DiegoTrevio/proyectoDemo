"""Graphiti temporal knowledge graph layer — bi-temporal facts in Neo4j.

Uses Graphiti Core for storing and querying facts with two time dimensions:
  - event_time: when the fact actually occurred
  - ingested_at: when the fact was recorded in the system

Connects to Neo4j (already in docker-compose).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config.settings import settings

logger = logging.getLogger("agentos.memory.graphiti")


@dataclass
class Fact:
    """A temporal fact in the knowledge graph."""
    subject: str
    predicate: str
    object: str
    event_time: datetime
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    source: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def triple(self) -> str:
        return f"({self.subject}) -[{self.predicate}]-> ({self.object})"


class GraphitiLayer:
    """Temporal knowledge graph using Graphiti Core + Neo4j."""

    def __init__(self):
        self._client = None
        self._fallback_facts: list[Fact] = []

        if settings.neo4j_uri and settings.neo4j_password:
            try:
                from graphiti_core import Graphiti
                from graphiti_core.utils.maintenance.graph_data_operations import clear_data

                self._client = Graphiti(
                    settings.neo4j_uri,
                    settings.neo4j_user,
                    settings.neo4j_password,
                )
                logger.info("Graphiti connected to Neo4j at %s", settings.neo4j_uri)
            except ImportError:
                logger.info("Graphiti not installed — using in-memory fallback")
            except Exception as e:
                logger.warning("Graphiti Neo4j connection failed: %s", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def initialize(self):
        """Initialize Graphiti indices (call once at startup)."""
        if self._client:
            try:
                await self._client.build_indices_and_constraints()
                logger.info("Graphiti indices built")
            except Exception as e:
                logger.warning("Failed to build Graphiti indices: %s", e)

    async def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        event_time: datetime | None = None,
        source: str = "",
        metadata: dict | None = None,
    ) -> Fact:
        """Add a fact to the knowledge graph.

        Args:
            subject: The subject entity (e.g. "Tesla")
            predicate: The relationship (e.g. "has_ceo")
            obj: The object entity (e.g. "Elon Musk")
            event_time: When the fact occurred (defaults to now)
            source: Source of the fact (e.g. task_id)
            metadata: Additional metadata

        Returns:
            The stored Fact.
        """
        now = datetime.now(timezone.utc)
        fact = Fact(
            subject=subject,
            predicate=predicate,
            object=obj,
            event_time=event_time or now,
            ingested_at=now,
            source=source,
            metadata=metadata or {},
        )

        if self._client:
            try:
                from graphiti_core import RawEpisode

                episode = RawEpisode(
                    name=f"{subject}_{predicate}_{obj}",
                    body=f"{subject} {predicate} {obj}",
                    source_description=source or "agentos",
                    reference_time=fact.event_time,
                )
                await self._client.add_episode(episode)
                logger.debug("Fact added to Neo4j: %s", fact.triple)
            except Exception as e:
                logger.warning("Failed to add fact to Graphiti: %s", e)
                self._fallback_facts.append(fact)
        else:
            self._fallback_facts.append(fact)

        return fact

    async def query_facts(
        self,
        query: str,
        time_range: tuple[datetime, datetime] | None = None,
        limit: int = 10,
    ) -> list[Fact]:
        """Query facts from the knowledge graph.

        Args:
            query: Natural language query.
            time_range: Optional (start, end) datetime tuple to filter by event_time.
            limit: Maximum number of results.

        Returns:
            List of matching Facts.
        """
        if self._client:
            try:
                results = await self._client.search(query, num_results=limit)
                facts = []
                for edge in results:
                    fact = Fact(
                        subject=getattr(edge, "source_node_name", str(edge)),
                        predicate=getattr(edge, "name", "related_to"),
                        object=getattr(edge, "target_node_name", ""),
                        event_time=getattr(edge, "created_at", datetime.now(timezone.utc)),
                        metadata={"graphiti_id": getattr(edge, "uuid", "")},
                    )

                    # Apply time range filter
                    if time_range:
                        start, end = time_range
                        if not (start <= fact.event_time <= end):
                            continue

                    facts.append(fact)
                    if len(facts) >= limit:
                        break

                return facts
            except Exception as e:
                logger.warning("Graphiti query failed, using fallback: %s", e)

        # Fallback: search in-memory facts
        return self._search_fallback(query, time_range, limit)

    async def get_entity_facts(self, entity: str, limit: int = 20) -> list[Fact]:
        """Get all facts related to a specific entity."""
        return await self.query_facts(entity, limit=limit)

    async def get_timeline(
        self,
        entity: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Fact]:
        """Get chronological timeline of facts about an entity."""
        time_range = None
        if start and end:
            time_range = (start, end)

        facts = await self.query_facts(entity, time_range=time_range, limit=50)
        facts.sort(key=lambda f: f.event_time)
        return facts

    def _search_fallback(
        self,
        query: str,
        time_range: tuple[datetime, datetime] | None,
        limit: int,
    ) -> list[Fact]:
        """Simple in-memory fact search."""
        query_lower = query.lower()
        results = []

        for fact in self._fallback_facts:
            # Time range filter
            if time_range:
                start, end = time_range
                if not (start <= fact.event_time <= end):
                    continue

            # Relevance check
            searchable = f"{fact.subject} {fact.predicate} {fact.object}".lower()
            if query_lower in searchable:
                results.append(fact)

        return results[:limit]

    def get_stats(self) -> dict:
        """Get statistics about the knowledge graph."""
        if self._client:
            return {"backend": "neo4j", "uri": settings.neo4j_uri}
        return {
            "backend": "in-memory",
            "total_facts": len(self._fallback_facts),
            "subjects": len(set(f.subject for f in self._fallback_facts)),
        }


# Singleton
graphiti = GraphitiLayer()
