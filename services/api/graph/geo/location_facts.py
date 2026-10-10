"""Canonical location-fact store (geographic360 G4.5 — internal write plane).

The geographic360 provider is a **read-only** projection over canonical location
truth. It can only be honest once a governed store exists for that truth, and no
such store existed before G4.5 — the provider's default reader answered an
honest ``missing`` for every subject. This module closes that gap with the ONE
canonical location-fact repository, ``location_facts``:

* ``record`` writes one validated :class:`~shared.geo.models.LocationFact`
  (the *internal* write boundary — repositories only, deliberately no public
  route/consent surface; a future context-capsule ingestion path calls this).
* ``active_facts_for_subject`` reads a subject's current facts, tenant-scoped.
* ``revoke`` / ``revoke_facts_for_subject`` perform a **governed soft-revoke**
  (``lifecycle_state`` ``active`` -> ``revoked`` + ``revoked_at`` stamp — never a
  hard delete), which is exactly the shape the DSR eraser over location facts
  needs (the population-tables erasure gap the blueprint calls out).

Rows are ``LocationFact`` JSON dumps plus a small lifecycle envelope on top:
``lifecycle_state`` (``active`` | ``revoked``), ``recorded_by``,
``revoked_at`` / ``revoked_by`` / ``revoke_reason``. The ``BaseRepository``
backend is shared: in-memory dicts when ``AETHER_ENV=local``, an auto-created
asyncpg JSONB table in production — the same store the population plane uses.
``find_many`` filters on top-level keys, so ``tenant_id`` / ``subject_type`` /
``subject_id`` / ``lifecycle_state`` are stored at the row's top level (they are
already top-level on the dumped ``LocationFact``; ``lifecycle_state`` is added).

Coordinates never leave this store as a rendered value: geographic360 echoes a
``coordinate_present`` flag only, and a ``revoked`` row is invisible to reads.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.geo.models import LocationFact

# Lifecycle state a stored location-fact row carries (soft-revoke envelope).
LOCATION_FACT_ACTIVE = "active"
LOCATION_FACT_REVOKED = "revoked"

# Default actor stamped on an internal ``record`` (an ingestion authority, not a
# data subject). The DSR erasure stamps its own actor/reason at revoke time.
LOCATION_FACT_RECORD_ACTOR = "location_fact_authority"

# Top-level envelope keys a reader must never mistake for LocationFact content.
_LIFECYCLE_KEYS = (
    "lifecycle_state",
    "recorded_by",
    "revoked_at",
    "revoked_by",
    "revoke_reason",
)


def _observed_sort_key(row: dict) -> str:
    """Chronological key for stored facts (observed_at, else valid/created)."""
    return str(row.get("observed_at") or row.get("valid_from") or row.get("created_at") or "")


class LocationFactRepository(BaseRepository):
    """Governed store for canonical ``LocationFact`` rows (table ``location_facts``).

    Backend-selected by the shared ``BaseRepository``: in-memory dicts when
    ``AETHER_ENV=local``, asyncpg JSONB table in production. Reads and revokes
    are tenant-scoped so one tenant can never see or erase another's facts.
    """

    def __init__(self) -> None:
        super().__init__("location_facts")

    async def record(
        self,
        fact: LocationFact,
        *,
        actor_id: str = LOCATION_FACT_RECORD_ACTOR,
    ) -> dict:
        """Write one canonical location fact (internal write boundary).

        Idempotent by ``location_id``: re-recording the same id replaces the
        row with a fresh active snapshot (a re-record after a revoke reactivates
        the fact). ``actor_id`` is stamped so the store's provenance is
        auditable without a public write surface.
        """
        data: dict[str, Any] = fact.model_dump(mode="json")
        existing = await self.find_by_id(fact.location_id)
        if existing is not None:
            # Replace the row entirely (a clean active snapshot) so no stale
            # lifecycle key survives a re-record.
            await self.delete(fact.location_id)
        data["lifecycle_state"] = LOCATION_FACT_ACTIVE
        data["recorded_by"] = actor_id
        return await self.insert(fact.location_id, data)

    async def active_facts_for_subject(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        limit: int = 10000,
    ) -> list[dict]:
        """Current (active) location facts for one subject, oldest -> newest.

        Revoked rows are invisible to reads — the soft-revoke honesty the DSR
        eraser relies on. ``subject_type`` is the geographic subject kind
        (``entity`` | ``population`` | ``source``).
        """
        rows = await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "lifecycle_state": LOCATION_FACT_ACTIVE,
            },
            limit=limit,
        )
        rows.sort(key=_observed_sort_key)
        return rows

    async def revoke(
        self,
        location_id: str,
        *,
        actor_id: str,
        reason: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Governed soft-revoke of one fact row (never a hard delete).

        Idempotent: revoking an already-revoked (or absent) row is a no-op.
        When ``tenant_id`` is given, a row belonging to another tenant is left
        untouched and ``None`` is returned (fail-closed defence in depth).
        """
        row = await self.find_by_id(location_id)
        if row is None or row.get("lifecycle_state") != LOCATION_FACT_ACTIVE:
            return row
        if tenant_id is not None and row.get("tenant_id") != tenant_id:
            return None
        now = utc_now().isoformat()
        row.update({
            "lifecycle_state": LOCATION_FACT_REVOKED,
            "revoked_at": now,
            "revoked_by": actor_id,
            "revoke_reason": reason,
        })
        return await self.update(location_id, row)

    async def revoke_facts_for_subject(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        *,
        actor_id: str,
        reason: str,
    ) -> int:
        """Revoke every *active* location fact for one subject (DSR erasure).

        Returns the number of governed revokes executed — the store's own
        receipt for the DSR propagation step. Never crosses tenants.
        """
        active = await self.active_facts_for_subject(tenant_id, subject_type, subject_id)
        revoked = 0
        for row in active:
            updated = await self.revoke(
                row["location_id"],
                actor_id=actor_id,
                reason=reason,
                tenant_id=tenant_id,
            )
            if updated is not None:
                revoked += 1
        return revoked


# Canonical singleton (mirrors ``population_repo`` / ``membership_repo``): one
# shared instance so reads through the geographic360 provider observe writes
# made through the internal boundary.
location_fact_repo = LocationFactRepository()

__all__ = [
    "LOCATION_FACT_ACTIVE",
    "LOCATION_FACT_RECORD_ACTOR",
    "LOCATION_FACT_REVOKED",
    "LocationFactRepository",
    "location_fact_repo",
]
