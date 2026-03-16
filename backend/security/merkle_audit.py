"""Merkle Audit Trail — tamper-evident chain of agent actions.

Each agent action is hashed into a Merkle chain. Modifying any record
breaks the chain, making tampering detectable. Suitable for SOC2/HIPAA.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("agentos.security.audit")


@dataclass
class AuditEvent:
    """A single event in the audit chain."""
    event_id: str
    task_id: str
    timestamp: str
    agent_id: str
    action: str
    input_hash: str
    output_hash: str
    model_used: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    prev_hash: str = ""
    event_hash: str = ""
    metadata: dict = field(default_factory=dict)

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this event (excluding event_hash)."""
        payload = (
            f"{self.event_id}|{self.task_id}|{self.timestamp}|"
            f"{self.agent_id}|{self.action}|{self.input_hash}|"
            f"{self.output_hash}|{self.model_used}|{self.tokens_used}|"
            f"{self.cost}|{self.prev_hash}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()


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


class MerkleAuditChain:
    """Append-only Merkle chain for agent action auditing."""

    def __init__(self):
        self._chains: dict[str, list[AuditEvent]] = {}  # task_id -> events
        self._counter = 0

    def add_event(
        self,
        task_id: str,
        agent_id: str,
        action: str,
        input_data: str = "",
        output_data: str = "",
        model_used: str = "",
        tokens_used: int = 0,
        cost: float = 0.0,
        metadata: dict | None = None,
    ) -> str:
        """Add an event to the task's audit chain. Returns the event hash."""
        self._counter += 1
        event_id = f"evt_{task_id}_{self._counter}"

        chain = self._chains.setdefault(task_id, [])
        prev_hash = chain[-1].event_hash if chain else "genesis"

        event = AuditEvent(
            event_id=event_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=agent_id,
            action=action,
            input_hash=self._hash(input_data),
            output_hash=self._hash(output_data),
            model_used=model_used,
            tokens_used=tokens_used,
            cost=cost,
            prev_hash=prev_hash,
            metadata=metadata or {},
        )
        event.event_hash = event.compute_hash()
        chain.append(event)

        logger.debug("Audit event %s: %s/%s hash=%s", event_id, agent_id, action, event.event_hash[:12])
        return event.event_hash

    def verify_chain(self, task_id: str) -> tuple[bool, str]:
        """Verify integrity of the entire chain for a task.

        Returns (is_valid, error_message).
        """
        chain = self._chains.get(task_id, [])
        if not chain:
            return True, "Empty chain"

        for i, event in enumerate(chain):
            # Verify hash
            expected_hash = event.compute_hash()
            if event.event_hash != expected_hash:
                return False, (
                    f"Hash mismatch at event {event.event_id} (position {i}): "
                    f"expected {expected_hash[:12]}, got {event.event_hash[:12]}"
                )

            # Verify chain linkage
            if i == 0:
                if event.prev_hash != "genesis":
                    return False, f"First event has wrong prev_hash: {event.prev_hash}"
            else:
                if event.prev_hash != chain[i - 1].event_hash:
                    return False, (
                        f"Chain broken at event {event.event_id} (position {i}): "
                        f"prev_hash doesn't match previous event"
                    )

        return True, f"Chain valid ({len(chain)} events)"

    def get_proof(self, task_id: str, event_id: str) -> MerkleProof | None:
        """Get a proof that an event exists in the chain."""
        chain = self._chains.get(task_id, [])

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

    def export_chain(self, task_id: str) -> list[dict]:
        """Export the full chain as JSON-serializable dicts (for audit/SOC2)."""
        chain = self._chains.get(task_id, [])
        return [
            {
                "event_id": e.event_id,
                "task_id": e.task_id,
                "timestamp": e.timestamp,
                "agent_id": e.agent_id,
                "action": e.action,
                "input_hash": e.input_hash,
                "output_hash": e.output_hash,
                "model_used": e.model_used,
                "tokens_used": e.tokens_used,
                "cost": e.cost,
                "prev_hash": e.prev_hash,
                "event_hash": e.event_hash,
                "metadata": e.metadata,
            }
            for e in chain
        ]

    def get_chain_stats(self, task_id: str) -> dict:
        """Get statistics for a task's audit chain."""
        chain = self._chains.get(task_id, [])
        if not chain:
            return {"events": 0, "valid": True}

        valid, msg = self.verify_chain(task_id)
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

    @staticmethod
    def _hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()


# Singleton
audit_chain = MerkleAuditChain()
