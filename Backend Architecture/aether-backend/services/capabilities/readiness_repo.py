"""Tenant-scoped capability readiness persistence + audit trail.

One row per ``(tenant_id, capability)`` records the CURRENT mission-canonical
readiness state (a :class:`~shared.certification.readiness.CredentialReadiness`
token) together with the evidence timestamp that justified it. Transitions are
monotonic:

* ``promote`` may only move the readiness rank UP (``readiness_rank``);
* ``demote`` may only move the readiness rank DOWN;

a violation raises :class:`ConflictError` — a promotion can never sneak a
demotion in and vice-versa, so the stored state is a strictly-monotone walk
over the canonical ranks.

Every state change (and every rejected attempt) is written to the canonical
tamper-evident security-audit ledger (:class:`AuditLedger`), extending the
existing audit conventions — no separate audit store is introduced. Evidence is
secret-sanitized before it is persisted or audited.

Production rows live in the ``capability_readiness`` table; the DDL intent is
listed in the integration pass's migration chain. Local mode uses the shared
in-memory stores, reset by ``reset_in_memory_stores``.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.certification.readiness import (
    CredentialReadiness,
    readiness_rank,
)
from shared.common.common import ConflictError, utc_now
from shared.logger.logger import get_logger
from services.security.audit_ledger import AuditLedger
from services.security.contracts import (
    SecurityAuditOutcome,
    sanitize_metadata,
)
from services.security.repositories import _ScopedRepo

logger = get_logger("aether.capability_readiness")

# Direction tokens written to the audit ledger and the ``last_change`` record.
DIRECTION_PROMOTION = "promotion"
DIRECTION_DEMOTION = "demotion"
DIRECTION_SEED = "seed"
DIRECTION_NOOP = "noop"


def _readiness_id(tenant_id: str, capability: str) -> str:
    """Stable record id for one ``(tenant_id, capability)`` row."""
    return f"{tenant_id}:{capability}"


class CapabilityReadinessRepository(_ScopedRepo):
    """Persists the latest capability-readiness snapshot per tenant+capability.

    Keyed by ``{tenant_id}:{capability}``. Tenant-scoped via the ``tenant_id``
    column so cross-tenant reads stay isolated.
    """

    def __init__(self) -> None:
        super().__init__("capability_readiness")

    async def get(self, tenant_id: str, capability: str) -> Optional[dict[str, Any]]:
        """Return the persisted readiness snapshot, or ``None`` when absent."""
        return await self.find_by_id(_readiness_id(tenant_id, capability))


class CapabilityReadinessService:
    """Monotonic promote/demote with audit trail for one tenant+capability."""

    def __init__(
        self,
        repo: Optional[CapabilityReadinessRepository] = None,
        ledger: Optional[AuditLedger] = None,
    ) -> None:
        self._repo = repo or CapabilityReadinessRepository()
        self._ledger = ledger or AuditLedger()

    # ── Reads ────────────────────────────────────────────────────────────────

    async def snapshot(
        self, tenant_id: str, capability: str
    ) -> Optional[dict[str, Any]]:
        """Return the persisted readiness snapshot, or ``None`` when absent."""
        return await self._repo.get(tenant_id, capability)

    # ── State changes (monotonic) ────────────────────────────────────────────

    async def seed(
        self,
        tenant_id: str,
        capability: str,
        *,
        target: CredentialReadiness,
        evidence: Optional[dict[str, Any]] = None,
        reason: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Create the first snapshot for a tenant+capability.

        ``seed`` is only legal when no snapshot exists yet; the stored rank is
        the baseline for every later monotonic transition.
        """
        existing = await self._repo.get(tenant_id, capability)
        if existing is not None:
            raise ConflictError(
                f"capability readiness already seeded for {capability!r} "
                f"tenant={tenant_id} state={existing.get('state')!r}"
            )
        now = utc_now().isoformat()
        target_state = _coerce(target)
        record: dict[str, Any] = {
            "readiness_id": _readiness_id(tenant_id, capability),
            "tenant_id": tenant_id,
            "capability": capability,
            "state": target_state.value,
            "evidence_timestamp": now,
            "evidence": sanitize_metadata(dict(evidence or {})),
            "promoted_at": None,
            "demoted_at": None,
            "last_change": {
                "direction": DIRECTION_SEED,
                "reason": reason,
                "actor": actor,
                "at": now,
            },
            "updated_at": now,
        }
        stored = await self._repo.insert(record["readiness_id"], record)
        await self._audit(
            tenant_id=tenant_id,
            capability=capability,
            from_state=None,
            to_state=target_state,
            direction=DIRECTION_SEED,
            reason=reason,
            actor=actor,
            outcome="allowed",
            evidence=record["evidence"],
        )
        return stored

    async def promote(
        self,
        tenant_id: str,
        capability: str,
        *,
        target: CredentialReadiness,
        evidence: Optional[dict[str, Any]] = None,
        reason: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Move readiness UP to ``target`` (rank must strictly increase).

        A target at or below the current rank is a monotonicity violation and
        raises :class:`ConflictError` (audited as ``blocked``).
        """
        return await self._apply_change(
            tenant_id,
            capability,
            target=target,
            evidence=evidence,
            reason=reason,
            actor=actor,
            direction=DIRECTION_PROMOTION,
        )

    async def demote(
        self,
        tenant_id: str,
        capability: str,
        *,
        target: CredentialReadiness,
        evidence: Optional[dict[str, Any]] = None,
        reason: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Move readiness DOWN to ``target`` (rank must strictly decrease).

        A target at or above the current rank is a monotonicity violation and
        raises :class:`ConflictError` (audited as ``blocked``).
        """
        return await self._apply_change(
            tenant_id,
            capability,
            target=target,
            evidence=evidence,
            reason=reason,
            actor=actor,
            direction=DIRECTION_DEMOTION,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _apply_change(
        self,
        tenant_id: str,
        capability: str,
        *,
        target: CredentialReadiness,
        evidence: Optional[dict[str, Any]] = None,
        reason: str = "",
        actor: str = "system",
        direction: str,
    ) -> dict[str, Any]:
        existing = await self._repo.get(tenant_id, capability)
        if existing is None:
            raise ConflictError(
                f"cannot {direction} unseeded capability readiness for "
                f"{capability!r} tenant={tenant_id} — call seed() first"
            )
        current = _coerce(existing.get("state"))
        target_state = _coerce(target)
        now = utc_now().isoformat()

        current_rank = readiness_rank(current)
        target_rank = readiness_rank(target_state)
        violates = (
            target_rank <= current_rank
            if direction == DIRECTION_PROMOTION
            else target_rank >= current_rank
        )
        if violates:
            await self._audit(
                tenant_id=tenant_id,
                capability=capability,
                from_state=current,
                to_state=target_state,
                direction=direction,
                reason=reason,
                actor=actor,
                outcome="blocked",
                evidence=sanitize_metadata(dict(evidence or {})),
            )
            raise ConflictError(
                f"monotonic {direction} violated for {capability!r} tenant={tenant_id}: "
                f"{current.value} (rank {current_rank}) -> {target_state.value} "
                f"(rank {target_rank})"
            )

        clean_evidence = sanitize_metadata(dict(evidence or {}))
        updated = dict(existing)
        updated["state"] = target_state.value
        updated["evidence_timestamp"] = now
        updated["evidence"] = clean_evidence
        updated["last_change"] = {
            "direction": direction,
            "reason": reason,
            "actor": actor,
            "at": now,
        }
        if direction == DIRECTION_PROMOTION:
            updated["promoted_at"] = now
        else:
            updated["demoted_at"] = now
        updated["updated_at"] = now
        stored = await self._repo.update(updated["readiness_id"], updated)
        await self._audit(
            tenant_id=tenant_id,
            capability=capability,
            from_state=current,
            to_state=target_state,
            direction=direction,
            reason=reason,
            actor=actor,
            outcome="allowed",
            evidence=clean_evidence,
        )
        logger.info(
            "capability_readiness %s capability=%s tenant=%s %s -> %s reason=%s",
            direction, capability, tenant_id, current.value, target_state.value,
            reason or "(none)",
        )
        return stored

    async def _audit(
        self,
        *,
        tenant_id: str,
        capability: str,
        from_state: Optional[CredentialReadiness],
        to_state: CredentialReadiness,
        direction: str,
        reason: str,
        actor: str,
        outcome: str,
        evidence: dict[str, Any],
    ) -> None:
        """Write one sanitized readiness change to the canonical audit ledger."""
        await self._ledger.record(
            actor_id=actor,
            actor_type="system",
            event_type="capability_readiness_changed",
            resource_type="capability_readiness",
            resource_id=_readiness_id(tenant_id, capability),
            action=direction,
            outcome=outcome,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            metadata={
                "capability": capability,
                "from_state": from_state.value if from_state is not None else None,
                "to_state": to_state.value,
                "reason": reason,
                "evidence": evidence,
            },
        )


def _coerce(state: Any) -> CredentialReadiness:
    """Coerce a raw state (enum member, value string) onto a readiness token."""
    try:
        return CredentialReadiness(state)
    except (KeyError, TypeError, ValueError):
        if isinstance(state, CredentialReadiness):
            return state
        raise ConflictError(f"invalid capability readiness state: {state!r}")


# Module-level singleton shared by routes / the revalidation worker.
capability_readiness_service = CapabilityReadinessService()


__all__ = [
    "DIRECTION_DEMOTION",
    "DIRECTION_NOOP",
    "DIRECTION_PROMOTION",
    "DIRECTION_SEED",
    "CapabilityReadinessRepository",
    "CapabilityReadinessService",
    "capability_readiness_service",
]
