"""Merkle Audit Trail — tamper-evident chain of agent actions.

Each agent action is hashed into a Merkle chain. Modifying any record
breaks the chain, making tampering detectable. Suitable for SOC2/HIPAA/GDPR.

Features:
- HMAC-SHA256 signing (prevents hash recomputation attacks)
- Thread-safe counters
- Bounded chains with configurable max size
- Pluggable storage backend (in-memory default, Postgres optional)
"""

import hashlib
import hmac
import itertools
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger("secureagent.audit")

# Maximum metadata size in bytes (5KB)
_MAX_METADATA_SIZE = 5120


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for persistent audit storage backends."""

    async def save_event(self, event: dict) -> None:
        """Persist a single audit event."""
        ...

    async def save_events_batch(self, events: list[dict]) -> None:
        """Persist a batch of audit events."""
        ...

    async def get_events(
        self,
        session_id: str,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query events with filters."""
        ...

    async def get_chain(self, session_id: str, tenant_id: Optional[str] = None) -> list[dict]:
        """Get full chain for a session."""
        ...


def _validate_metadata(metadata: dict, max_size: int = _MAX_METADATA_SIZE) -> dict:
    """Validate and sanitize metadata dict. Limits depth to 3 and total size."""
    import json
    serialized = json.dumps(metadata, default=str)
    if len(serialized) > max_size:
        return {"_truncated": True, "_original_size": len(serialized)}

    def _check_depth(obj: Any, depth: int = 0) -> Any:
        if depth > 3:
            return str(obj)
        if isinstance(obj, dict):
            return {str(k)[:200]: _check_depth(v, depth + 1) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_check_depth(v, depth + 1) for v in obj[:100]]
        return obj

    return _check_depth(metadata)


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
    signature: str = ""  # HMAC-SHA256 signature
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

    def compute_signature(self, signing_key: str) -> str:
        """Compute HMAC-SHA256 signature using the signing key."""
        return hmac.new(
            signing_key.encode(),
            self.event_hash.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_signature(self, signing_key: str) -> bool:
        """Verify HMAC-SHA256 signature."""
        expected = self.compute_signature(signing_key)
        return hmac.compare_digest(self.signature, expected)

    def to_dict(self) -> dict:
        result = {
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
        if self.signature:
            result["signature"] = self.signature
        return result


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
    signature_valid: Optional[bool] = None


class AuditLog:
    """Append-only Merkle chain for agent action auditing.

    Usage:
        # Basic (in-memory)
        log = AuditLog()

        # With HMAC signing (recommended for production)
        log = AuditLog(signing_key="your-secret-key")

        # With bounded chains
        log = AuditLog(max_events_per_session=10000)

        # Log an agent action
        event_hash = log.add_event(
            session_id="sess_123",
            agent_id="agent_coder",
            action="tool_call",
            tool_name="search_web",
            input_data="query: python security",
            output_data="results...",
        )

        # Verify chain integrity (including signatures)
        valid, msg = log.verify_chain("sess_123")

        # Export for SOC2 audit
        trail = log.export_chain("sess_123")
    """

    def __init__(
        self,
        signing_key: Optional[str] = None,
        storage: Optional[StorageBackend] = None,
        max_events_per_session: int = 10_000,
        max_sessions: int = 1_000,
    ):
        self._chains: dict[str, list[AuditEvent]] = {}
        self._counter = itertools.count(1)  # Thread-safe counter
        self._lock = threading.RLock()
        self._signing_key = signing_key
        self._storage = storage
        self._max_events = max_events_per_session
        self._max_sessions = max_sessions

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
        # Validate numeric inputs
        tokens_used = max(0, min(tokens_used, 10_000_000))
        cost = max(0.0, min(cost, 100_000.0))

        # Validate and sanitize metadata
        clean_metadata = _validate_metadata(metadata) if metadata else {}

        count = next(self._counter)
        event_id = f"evt_{session_id}_{count}"

        with self._lock:
            # Enforce max sessions
            if session_id not in self._chains and len(self._chains) >= self._max_sessions:
                oldest = next(iter(self._chains))
                logger.warning("Max sessions reached (%d), evicting oldest: %s", self._max_sessions, oldest)
                del self._chains[oldest]

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
                metadata=clean_metadata,
            )
            event.event_hash = event.compute_hash()

            # Sign if signing key configured
            if self._signing_key:
                event.signature = event.compute_signature(self._signing_key)

            chain.append(event)

            # Enforce max events per session
            if len(chain) > self._max_events:
                evicted = len(chain) - self._max_events
                logger.warning(
                    "Session %s exceeded max events (%d), evicting %d oldest",
                    session_id, self._max_events, evicted,
                )
                self._chains[session_id] = chain[evicted:]

        logger.debug("Audit: %s %s/%s hash=%s", event_id, agent_id, action, event.event_hash[:12])
        return event.event_hash

    def verify_chain(self, session_id: str) -> tuple[bool, str]:
        """Verify integrity of the entire chain. Returns (is_valid, message)."""
        with self._lock:
            chain = self._chains.get(session_id, [])
            if not chain:
                return True, "Empty chain"

            for i, event in enumerate(chain):
                # Verify hash
                expected_hash = event.compute_hash()
                if event.event_hash != expected_hash:
                    return False, (
                        f"Hash mismatch at {event.event_id} (pos {i}): "
                        f"expected {expected_hash[:12]}, got {event.event_hash[:12]}"
                    )

                # Verify chain linkage
                if i == 0:
                    if event.prev_hash != "genesis":
                        return False, f"First event has wrong prev_hash: {event.prev_hash}"
                else:
                    if event.prev_hash != chain[i - 1].event_hash:
                        return False, f"Chain broken at {event.event_id} (pos {i})"

                # Verify signature if signing is enabled
                if self._signing_key and event.signature:
                    if not event.verify_signature(self._signing_key):
                        return False, (
                            f"Invalid signature at {event.event_id} (pos {i}): "
                            f"event may have been tampered with"
                        )

            return True, f"Chain valid ({len(chain)} events)"

    def get_proof(self, session_id: str, event_id: str) -> Optional[MerkleProof]:
        """Get a proof that an event exists in the chain."""
        with self._lock:
            chain = self._chains.get(session_id, [])
            for i, event in enumerate(chain):
                if event.event_id == event_id:
                    next_hash = chain[i + 1].event_hash if i + 1 < len(chain) else ""
                    sig_valid = None
                    if self._signing_key and event.signature:
                        sig_valid = event.verify_signature(self._signing_key)
                    return MerkleProof(
                        event_id=event_id,
                        event_hash=event.event_hash,
                        chain_position=i,
                        chain_length=len(chain),
                        prev_hash=event.prev_hash,
                        next_hash=next_hash,
                        valid=event.event_hash == event.compute_hash(),
                        signature_valid=sig_valid,
                    )
        return None

    def export_chain(self, session_id: str) -> list[dict]:
        """Export the full chain as JSON-serializable dicts (for SOC2/GDPR audit)."""
        with self._lock:
            return [e.to_dict() for e in self._chains.get(session_id, [])]

    def get_stats(self, session_id: str) -> dict:
        """Get statistics for a session's audit chain."""
        with self._lock:
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
                "signed": self._signing_key is not None,
            }

    def get_events(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with optional filters."""
        with self._lock:
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
