"""Security Audit Event Ledger.

Tamper-evident audit trail for sensitive governance actions. Each event is
sanitized (no secrets) and assigned an integrity_hash chained to the previous
event for the same tenant, so deletion or reordering is detectable.

The ledger answers: who accessed what, who approved what, what policy allowed or
blocked an action.

The hash-chain math itself (``compute_integrity_hash`` / ``verify_chain``) now
lives in ``shared/integrity/hash_chain.py`` as a table-agnostic primitive —
see ``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md`` Program 1, M1. This
module owns only the audit-event-specific pieces: which fields are canonical,
the per-tenant chain-tail cache, and the audit-specific v1/v2 hash-shape
tolerance. Behavior is unchanged from before the extraction.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.integrity import hash_chain
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


def _canonical_fields(event: SecurityAuditEvent, *, include_detail: bool = True) -> dict[str, Any]:
    """The audit event's canonical fields to hash (excludes prev_hash — the
    shared primitive adds that itself so every caller chains consistently).
    """
    payload: dict[str, Any] = {
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
        # created_at is intentionally excluded: the persistence layer assigns its
        # own created_at on insert, so hashing it would break verification. Order
        # and tamper-evidence come from the chained prev_hash + immutable ids.
    }
    if include_detail:
        # v2: persisted "what / from where" detail is part of the tamper-evident
        # record, so editing metadata/ip_address/user_agent breaks verify_chain().
        # metadata is already secret-sanitized at record() time.
        payload["metadata"] = event.metadata
        payload["ip_address"] = event.ip_address
        payload["user_agent"] = event.user_agent
    return payload


def compute_integrity_hash(event: SecurityAuditEvent, prev_hash: str = "", *, include_detail: bool = True) -> str:
    return hash_chain.compute_integrity_hash(
        _canonical_fields(event, include_detail=include_detail), prev_hash
    )


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
        against the first tenant's tail and falsely reported as broken. The
        walk/compare/advance mechanics themselves are the shared, table-agnostic
        ``hash_chain.verify_chain`` primitive; this method supplies only the
        audit-event-specific field/partition/variant accessors.
        """
        raw_events = (
            await self._repo.list_for_tenant(tenant_id or "", limit=10_000)
            if tenant_id else await self._repo.list_all(limit=10_000)
        )
        # (raw dict, parsed model) pairs — kept together because `_chain_seq` is
        # a repository-only bookkeeping field, not part of the SecurityAuditEvent
        # schema, so it must be read off the raw dict for sort ordering.
        parsed = [(raw, SecurityAuditEvent(**raw)) for raw in raw_events]

        result = hash_chain.verify_chain(
            parsed,
            partition_key=lambda item: item[1].tenant_id or "",
            sort_key=lambda item: (
                item[1].tenant_id or "",
                item[0].get("created_at", ""),
                item[0].get("_chain_seq", 0),
            ),
            # v2 events hash metadata/ip/user_agent; pre-existing v1 events do
            # not. Accept either so historical, untouched rows verify cleanly
            # after the canonical shape changed (backcompat), while still
            # detecting tampering of v2 events. v2 is listed first so it is the
            # canonical fallback the shared primitive advances the chain on
            # when a record's stored hash is missing.
            canonical_field_variants=lambda item: [
                _canonical_fields(item[1], include_detail=True),
                _canonical_fields(item[1], include_detail=False),
            ],
            stored_hash=lambda item: item[1].integrity_hash,
            record_id=lambda item: item[1].audit_event_id,
        )
        return {
            "tenant_id": tenant_id,
            "events_checked": result["records_checked"],
            "chains_verified": result["chains_verified"],
            "chain_intact": result["chain_intact"],
            "broken_event_ids": result["broken_record_ids"],
        }


# Module-level singleton shared by PolicyEngine / AccessControlService / routes.
audit_ledger = AuditLedger()
