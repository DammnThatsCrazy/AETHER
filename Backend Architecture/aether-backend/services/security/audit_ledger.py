"""Security Audit Event Ledger.

Tamper-evident audit trail for sensitive governance actions. Each event is
sanitized (no secrets) and assigned an integrity_hash chained to the previous
event for the same tenant, so deletion or reordering is detectable.

The ledger answers: who accessed what, who approved what, what policy allowed or
blocked an action.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from shared.logger.logger import get_logger

from .contracts import (
    ActorType,
    SecurityAuditEvent,
    SecurityAuditOutcome,
    sanitize_metadata,
)
from .repositories import SecurityAuditEventRepository

logger = get_logger("aether.security.audit_ledger")

# Per-tenant tail hash, used to chain integrity hashes in the in-memory path and
# as a best-effort chain anchor in production. Keyed by tenant_id ("" for global).
_TENANT_TAIL: dict[str, str] = {}
# Per-tenant monotonic sequence so the chain has a deterministic order even when
# multiple events share an identical millisecond timestamp.
_TENANT_SEQ: dict[str, int] = {}


def _canonical(event: SecurityAuditEvent, prev_hash: str) -> str:
    payload = {
        "audit_event_id": event.audit_event_id,
        "tenant_id": event.tenant_id,
        "actor_id": event.actor_id,
        "actor_type": event.actor_type,
        "event_type": event.event_type,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "action": event.action,
        "outcome": event.outcome,
        "policy_decision_id": event.policy_decision_id,
        # Persisted "what / from where" detail is part of the tamper-evident
        # record: hashing it means edits to metadata, ip_address, or user_agent
        # break verify_chain(). metadata is already secret-sanitized at record().
        "metadata": event.metadata,
        "ip_address": event.ip_address,
        "user_agent": event.user_agent,
        # created_at is intentionally excluded: the persistence layer assigns its
        # own created_at on insert, so hashing it would break verification. Order
        # and tamper-evidence come from the chained prev_hash + immutable ids.
        "prev_hash": prev_hash,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def compute_integrity_hash(event: SecurityAuditEvent, prev_hash: str = "") -> str:
    return hashlib.sha256(_canonical(event, prev_hash).encode("utf-8")).hexdigest()


class AuditLedger:
    """Service wrapper around SecurityAuditEventRepository."""

    def __init__(self, repo: Optional[SecurityAuditEventRepository] = None) -> None:
        self._repo = repo or SecurityAuditEventRepository()

    async def record(
        self,
        *,
        actor_id: str,
        actor_type: ActorType,
        event_type: str,
        resource_type: str,
        action: str,
        outcome: SecurityAuditOutcome,
        tenant_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SecurityAuditEvent:
        event = SecurityAuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            outcome=outcome,
            policy_decision_id=policy_decision_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=sanitize_metadata(metadata),
        )
        chain_key = tenant_id or ""
        prev_hash = _TENANT_TAIL.get(chain_key, "")
        event.integrity_hash = compute_integrity_hash(event, prev_hash)
        _TENANT_TAIL[chain_key] = event.integrity_hash
        seq = _TENANT_SEQ.get(chain_key, 0) + 1
        _TENANT_SEQ[chain_key] = seq

        record = event.model_dump()
        record["_chain_seq"] = seq
        await self._repo.insert(event.audit_event_id, record)
        logger.info(
            "audit_event recorded type=%s action=%s outcome=%s tenant=%s",
            event_type, action, outcome, tenant_id,
        )
        return event

    async def verify_chain(self, tenant_id: Optional[str] = None) -> dict[str, Any]:
        """Re-walk events and confirm the integrity_hash chain holds.

        Events are chained per tenant (chain_key = tenant_id or ""), so a global
        verification (tenant_id omitted) must track a separate previous hash per
        chain — otherwise the first event of the second tenant would be compared
        against the first tenant's tail and falsely reported as broken.
        """
        raw_events = (
            await self._repo.list_for_tenant(tenant_id or "", limit=10_000)
            if tenant_id else await self._repo.list_all(limit=10_000)
        )
        events = sorted(
            raw_events,
            key=lambda e: (e.get("tenant_id") or "", e.get("created_at", ""), e.get("_chain_seq", 0)),
        )
        prev_by_chain: dict[str, str] = {}
        broken: list[str] = []
        for raw in events:
            ev = SecurityAuditEvent(**raw)
            chain_key = ev.tenant_id or ""
            prev = prev_by_chain.get(chain_key, "")
            expected = compute_integrity_hash(ev, prev)
            if ev.integrity_hash != expected:
                broken.append(ev.audit_event_id)
            prev_by_chain[chain_key] = ev.integrity_hash or expected
        return {
            "tenant_id": tenant_id,
            "events_checked": len(events),
            "chains_verified": len(prev_by_chain),
            "chain_intact": not broken,
            "broken_event_ids": broken,
        }


# Module-level singleton shared by PolicyEngine / AccessControlService / routes.
audit_ledger = AuditLedger()
