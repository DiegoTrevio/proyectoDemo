"""Merkle Audit Trail — tamper-evident chain of agent actions.

Each agent action is hashed into a Merkle chain. Modifying any record
breaks the chain, making tampering detectable. Suitable for SOC2/HIPAA/GDPR.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("secureagent.audit")


@dataclass
class AuditEvent:
    """A single event in the audit chain."""
    event_id: str
    session_id: str
    timestamp: str
    agent_id: str
    action: str
    input_hash: str
    output_hash: str
    tool_name: str = ""
    model_used: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    risk_level: str = "low"
    prev_hash: str = ""
    event_hash: str = ""
    metadata: dict = field(default_factory=dict)

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this event."""
        payload = (
            f"{self.event_id}|{self.session_id}|{self.timestamp}|"
            f"{self.agent_id}|{self.action}|{self.input_hash}|"
            f"{self.output_hash}|{self.tool_name}|{self.model_used}|"
            f"{self.tokens_used}|{self.cost}|{self.prev_hash}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "action": self.action,
            "tool_name": self.tool_name,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "cost": self.cost,
            "risk_level": self.risk_level,
            "prev_hash": self.prev_hash,
            "event_hash": self.event_hash,
            "metadata": self.metadata,
        }


@dataclass
class MerkleProof:
    """Proof that an event exists in the chain."""
    event_id: str
    event_hash: str
    chain_position: int
    chain_length: int
    prev_hash: str
    next_hash: str
    valid: bool


class AuditLog:
    """Append-only Merkle chain for agent action auditing.

    Usage:
        log = AuditLog()

        # Log an agent action
        event_hash = log.add_event(
            session_id="sess_123",
            agent_id="agent_coder",
            action="tool_call",
            tool_name="search_web",
            input_data="query: python security",
            output_data="results...",
        )

        # Verify chain integrity
        valid, msg = log.verify_chain("sess_123")

        # Export for SOC2 audit
        trail = log.export_chain("sess_123")
    """

    def __init__(self):
        self._chains: dict[str, list[AuditEvent]] = {}
        self._counter = 0

    def add_event(
        self,
        session_id: str,
        agent_id: str,
        action: str,
        tool_name: str = "",
        input_data: str = "",
        output_data: str = "",
        model_used: str = "",
        tokens_used: int = 0,
        cost: float = 0.0,
        risk_level: str = "low",
        metadata: Optional[dict] = None,
    ) -> str:
        """Add an event to the session's audit chain. Returns the event hash."""
        self._counter += 1
        event_id = f"evt_{session_id}_{self._counter}"

        chain = self._chains.setdefault(session_id, [])
        prev_hash = chain[-1].event_hash if chain else "genesis"

        event = AuditEvent(
            event_id=event_id,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=agent_id,
            action=action,
            tool_name=tool_name,
            input_hash=self._hash(input_data),
            output_hash=self._hash(output_data),
            model_used=model_used,
            tokens_used=tokens_used,
            cost=cost,
            risk_level=risk_level,
            prev_hash=prev_hash,
            metadata=metadata or {},
        )
        event.event_hash = event.compute_hash()
        chain.append(event)

        logger.debug("Audit: %s %s/%s hash=%s", event_id, agent_id, action, event.event_hash[:12])
        return event.event_hash

    def verify_chain(self, session_id: str) -> tuple[bool, str]:
        """Verify integrity of the entire chain. Returns (is_valid, message)."""
        chain = self._chains.get(session_id, [])
        if not chain:
            return True, "Empty chain"

        for i, event in enumerate(chain):
            expected_hash = event.compute_hash()
            if event.event_hash != expected_hash:
                return False, (
                    f"Hash mismatch at {event.event_id} (pos {i}): "
                    f"expected {expected_hash[:12]}, got {event.event_hash[:12]}"
                )
            if i == 0:
                if event.prev_hash != "genesis":
                    return False, f"First event has wrong prev_hash: {event.prev_hash}"
            else:
                if event.prev_hash != chain[i - 1].event_hash:
                    return False, f"Chain broken at {event.event_id} (pos {i})"

        return True, f"Chain valid ({len(chain)} events)"

    def get_proof(self, session_id: str, event_id: str) -> Optional[MerkleProof]:
        """Get a proof that an event exists in the chain."""
        chain = self._chains.get(session_id, [])
        for i, event in enumerate(chain):
            if event.event_id == event_id:
                next_hash = chain[i + 1].event_hash if i + 1 < len(chain) else ""
                return MerkleProof(
                    event_id=event_id,
                    event_hash=event.event_hash,
                    chain_position=i,
                    chain_length=len(chain),
                    prev_hash=event.prev_hash,
                    next_hash=next_hash,
                    valid=event.event_hash == event.compute_hash(),
                )
        return None

    def export_chain(self, session_id: str) -> list[dict]:
        """Export the full chain as JSON-serializable dicts (for SOC2/GDPR audit)."""
        return [e.to_dict() for e in self._chains.get(session_id, [])]

    def get_stats(self, session_id: str) -> dict:
        """Get statistics for a session's audit chain."""
        chain = self._chains.get(session_id, [])
        if not chain:
            return {"events": 0, "valid": True}
        valid, msg = self.verify_chain(session_id)
        return {
            "events": len(chain),
            "valid": valid,
            "message": msg,
            "total_tokens": sum(e.tokens_used for e in chain),
            "total_cost": sum(e.cost for e in chain),
            "agents": list(set(e.agent_id for e in chain)),
            "first_event": chain[0].timestamp,
            "last_event": chain[-1].timestamp,
        }

    def get_events(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with optional filters."""
        chain = self._chains.get(session_id, [])
        results = []
        for event in chain:
            if agent_id and event.agent_id != agent_id:
                continue
            if action and event.action != action:
                continue
            results.append(event.to_dict())
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()
