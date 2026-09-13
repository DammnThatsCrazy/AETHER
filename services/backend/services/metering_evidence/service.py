"""Metering Evidence (§3.16).

Every metered event carries an auditable evidence record explaining *why* it was
billed or excluded. Records are **additive** (their own ``metering_evidence``
table) and dedupe is **fail-closed for double billing**: a repeated
``dedupe_key`` within a tenant is recorded but marked non-billable with
``excluded_reason="duplicate"`` so it can never be billed twice, while the
evidence trail is preserved.

``MeteringEvidenceService.record(...)`` writes a :class:`MeteredEvent`.
``explain(metered_event_id)`` returns the stored evidence record.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.security.repositories import _ScopedRepo

logger = get_logger("aether.metering_evidence")

EXCLUDED_DUPLICATE = "duplicate"


def _now_iso() -> str:
    return utc_now().isoformat()


@dataclass
class MeteredEvent:
    """A single metering-evidence record (§3.16)."""

    metered_event_id: str
    tenant_id: str
    source_path: str
    source_provider: str
    event_id: str
    dedupe_key: str
    billable: bool
    billing_reason: str
    excluded_reason: Optional[str]
    schema_version: str
    received_at: str
    metered_at: str
    usage_dimension: str
    quantity: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MeteringEvidenceRepository(_ScopedRepo):
    """Persists :class:`MeteredEvent` records (table ``metering_evidence``)."""

    def __init__(self) -> None:
        super().__init__("metering_evidence")

    async def find_by_dedupe(
        self, tenant_id: str, dedupe_key: str,
    ) -> Optional[dict[str, Any]]:
        """Return the earliest existing record for a tenant + dedupe_key, if any.

        Scoped to the tenant so identical dedupe_keys across different tenants
        are independent (no cross-tenant dedupe).
        """
        if not dedupe_key:
            return None
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "dedupe_key": dedupe_key},
            limit=1,
            sort_by="created_at",
            sort_order="asc",
        )
        return rows[0] if rows else None


class MeteringEvidenceService:
    """Records and explains metering evidence with per-tenant dedupe."""

    def __init__(self, repo: Optional[MeteringEvidenceRepository] = None) -> None:
        self._repo = repo or MeteringEvidenceRepository()

    async def record(
        self,
        *,
        tenant_id: str,
        source_path: str,
        event_id: str,
        dedupe_key: str,
        source_provider: str = "",
        usage_dimension: str = "events",
        quantity: float = 1,
        schema_version: str = "1.0.0",
        billable: bool = True,
        billing_reason: str = "metered",
        excluded_reason: Optional[str] = None,
        metered_event_id: Optional[str] = None,
        received_at: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record a metered event.

        If ``dedupe_key`` already exists for this tenant, the new record is
        forced non-billable with ``excluded_reason="duplicate"`` (double-billing
        protection) and its ``billing_reason`` references the original event.
        """
        metered_event_id = metered_event_id or uuid.uuid4().hex
        received = received_at or _now_iso()

        duplicate_of = await self._repo.find_by_dedupe(tenant_id, dedupe_key)
        if duplicate_of is not None:
            billable = False
            excluded_reason = EXCLUDED_DUPLICATE
            original_id = duplicate_of.get("metered_event_id") or duplicate_of.get("id")
            billing_reason = f"duplicate_of:{original_id}"

        event = MeteredEvent(
            metered_event_id=metered_event_id,
            tenant_id=tenant_id,
            source_path=source_path,
            source_provider=source_provider,
            event_id=event_id,
            dedupe_key=dedupe_key,
            billable=billable,
            billing_reason=billing_reason,
            excluded_reason=excluded_reason,
            schema_version=schema_version,
            received_at=received,
            metered_at=_now_iso(),
            usage_dimension=usage_dimension,
            quantity=quantity,
            metadata=metadata or {},
        )
        stored = await self._repo.insert(metered_event_id, event.to_dict())
        logger.info(
            "metering_evidence recorded id=%s tenant=%s billable=%s excluded=%s",
            metered_event_id, tenant_id, event.billable, event.excluded_reason,
        )
        return stored

    async def explain(
        self, metered_event_id: str, tenant_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Return the evidence record for ``metered_event_id`` (or None).

        When ``tenant_id`` is provided, the record is only returned if it belongs
        to that tenant (fail-closed tenant isolation).
        """
        record = await self._repo.find_by_id(metered_event_id)
        if record is None:
            return None
        if tenant_id is not None and record.get("tenant_id") != tenant_id:
            return None
        return record
