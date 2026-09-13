"""Durable stores for the Rights Authority (blueprint §15).

``rights_decisions``  — durable RightsDecision records (blueprint §4/§17).
``rights_lineage``    — artifact → parent/source/decision rights linkage (§5.2).
``rights_impacts``    — revocation/deletion/restatement impact state (§10).

Every repository subclasses BaseRepository (JSONB-backed in production,
in-memory dicts for AETHER_ENV=local) via the shared tenant-scoped ``_ScopedRepo``
from ``services/security/repositories.py``, mirroring ``services/policy/`` and
``services/security/`` conventions. Records are serialized pydantic bodies; the
canonical row key is carried both as the DB ``id`` and inside the JSON body.
"""
from __future__ import annotations

from typing import Optional

from services.security.repositories import _ScopedRepo
from services.rights_authority.contracts import (
    ALLOWED_REMEDIATION_STATES,
    RightsDecision,
    RightsImpact,
    RightsLineage,
)

__all__ = [
    "RightsDecisionRepository",
    "RightsLineageRepository",
    "RightsImpactRepository",
    "rights_decision_repository",
    "rights_lineage_repository",
    "rights_impact_repository",
]


def _iso_dt(value: Optional[str]):
    """Parse an ISO instant via the shared temporal parser (aware UTC, None-safe)."""
    if not value:
        return None
    from shared.common.common import parse_event_time

    return parse_event_time(value)


class RightsDecisionRepository(_ScopedRepo):
    """Tenant-scoped durable store of RightsDecision records (table: rights_decisions)."""

    def __init__(self) -> None:
        super().__init__("rights_decisions")

    async def record(
        self,
        decision: RightsDecision | dict,
        *,
        identity_key: Optional[str] = None,
    ) -> dict:
        """Persist a decision idempotently by decision_id.

        ``decision`` may be a ``RightsDecision`` model or an already-dumped row
        dict (revocation pipeline records a deny decision built as a dict);
        both are normalized to a JSON body here so every caller survives the
        real repository boundary.

        ``identity_key`` is the decision-idempotency key (blueprint §17: tenant +
        actor + purpose + artifact + requested_use + destination + policy_version +
        as-of). It is stored in the JSON body so identical requests can be re-found
        without conflicting decision rows.
        """
        body = (
            decision.model_dump(mode="json")
            if hasattr(decision, "model_dump")
            else dict(decision)
        )
        body["decision_id"] = body.get("decision_id") or getattr(
            decision, "decision_id", None
        )
        body["tenant_id"] = body.get("tenant_id") or getattr(decision, "tenant_id", None)
        if identity_key:
            body["identity_key"] = identity_key
        return await self.insert(body["decision_id"], body)

    async def get(self, decision_id: str) -> Optional[dict]:
        return await self.find_by_id(decision_id)

    async def find_by_identity(
        self,
        tenant_id: str,
        identity_key: str,
        limit: int = 1,
    ) -> Optional[dict]:
        """Return the recorded decision for a §17 identity key, if any."""
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "identity_key": identity_key},
            limit=limit,
        )
        return rows[0] if rows else None

    async def list_for_tenant(
        self, tenant_id: str, limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        return await super().list_for_tenant(tenant_id, limit=limit, offset=offset)

    async def list_known_as_of(
        self,
        as_of: str,
        tenant_id: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Return decisions whose effective time is at or before ``as_of``.

        Used for historical replay / ORIGINAL_RIGHTS views (blueprint §11): the
        durable store is append-only, so "known as of" is a filter over recorded
        decisions, not a delete.
        """
        if tenant_id is not None:
            rows = await self.list_for_tenant(tenant_id, limit=limit)
        else:
            rows = await self.list_all(limit=limit)
        target = _iso_dt(as_of)
        if target is None:
            return []
        result = []
        for row in rows:
            effective = _iso_dt(
                row.get("effective_as_of") or row.get("evaluated_at")
            )
            if effective is not None and effective <= target:
                result.append(row)
        return result


class RightsLineageRepository(_ScopedRepo):
    """Artifact → parent rights linkage (table: rights_lineage; key: artifact_id)."""

    def __init__(self) -> None:
        super().__init__("rights_lineage")

    async def record(self, lineage: RightsLineage) -> dict:
        body = lineage.model_dump(mode="json")
        body["artifact_id"] = lineage.artifact_id
        body["tenant_id"] = lineage.tenant_id or ""
        return await self.insert(lineage.artifact_id, body)

    async def get(self, artifact_id: str) -> Optional[dict]:
        return await self.find_by_id(artifact_id)

    async def list_for_artifact(self, artifact_id: str) -> list[dict]:
        row = await self.find_by_id(artifact_id)
        return [row] if row else []


class RightsImpactRepository(_ScopedRepo):
    """Revocation/deletion/restatement impact state (table: rights_impacts; key: impact_id)."""

    def __init__(self) -> None:
        super().__init__("rights_impacts")

    async def record(self, impact: RightsImpact | dict) -> dict:
        """Persist an impact row (``RightsImpact`` model or dumped dict).

        Impact producers (``impact.persist_impact_items``, revocation pipeline)
        emit row dicts; normalizing here keeps the real repository boundary safe
        for model and dict callers alike.
        """
        body = (
            impact.model_dump(mode="json")
            if hasattr(impact, "model_dump")
            else dict(impact)
        )
        body["impact_id"] = body.get("impact_id") or getattr(impact, "impact_id", None)
        if body.get("tenant_id") is None:
            body["tenant_id"] = getattr(impact, "tenant_id", None)
        return await self.insert(body["impact_id"], body)

    async def get(self, impact_id: str) -> Optional[dict]:
        return await self.find_by_id(impact_id)

    async def list_pending(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Impacts still awaiting remediation (pending / in_progress / untriaged).

        ``None`` / ``unknown`` remediation state is never "complete", so untriaged
        impacts are returned as pending rather than silently dropped.
        """
        if tenant_id is not None:
            rows = await self.list_for_tenant(tenant_id, limit=limit)
        else:
            rows = await self.list_all(limit=limit)
        pending = {"pending", "in_progress", "unknown"}
        return [
            row for row in rows
            if (row.get("remediation_state") or "pending").lower() in pending
        ]

    async def update_state(self, impact_id: str, state: str) -> dict:
        normalized = (state or "").strip().lower()
        if normalized not in ALLOWED_REMEDIATION_STATES:
            allowed = ", ".join(sorted(ALLOWED_REMEDIATION_STATES))
            raise ValueError(
                f"invalid remediation_state {state!r} for {impact_id}; "
                f"allowed: {allowed}"
            )
        body = await self.find_by_id_or_fail(impact_id)
        body["remediation_state"] = normalized
        return await self.update(impact_id, body)


# ── Module-level singletons (mirrors services/security + services/policy) ──────
rights_decision_repository = RightsDecisionRepository()
rights_lineage_repository = RightsLineageRepository()
rights_impact_repository = RightsImpactRepository()
