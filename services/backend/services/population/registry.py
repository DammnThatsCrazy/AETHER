"""
Population Registry — Central store for all population objects and memberships.

Uses existing BaseRepository pattern (asyncpg in prod, in-memory in local).
"""

from __future__ import annotations

import json
from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import BadRequestError, ConflictError, utc_now
from shared.logger.logger import get_logger, metrics
from services.population.models import (
    MembershipBasis,
    MembershipState,
    PopulationType,
    make_definition_version_record,
    make_membership_record,
    make_population_record,
)

logger = get_logger("aether.population.registry")


def _canonical_definition(definition: Optional[dict]) -> dict:
    """Canonical view of a definition dict for equality/hash comparisons."""
    return definition or {}


def _definitions_equal(a: Optional[dict], b: Optional[dict]) -> bool:
    return json.dumps(
        _canonical_definition(a), sort_keys=True, separators=(",", ":")
    ) == json.dumps(_canonical_definition(b), sort_keys=True, separators=(",", ":"))


class PopulationDefinitionRepository(BaseRepository):
    """Append-only immutable ledger of population-definition versions (P3.2).

    Each version is a population's *definition contract*: a row whose id is
    deterministic over ``(population_id, definition_version)`` so a version can
    be published at most once. The ``populations.definition`` field is only the
    current projection; this ledger is the authoritative history a recompute /
    audit / population360 ``transitions`` reads. Nothing here is ever updated.
    """

    def __init__(self) -> None:
        super().__init__("population_definition_versions")

    async def record(
        self,
        population_id: str,
        definition_version: str,
        definition: dict,
        *,
        reason: str = "",
        created_by: str = "population_api",
        supersedes_version: Optional[str] = None,
    ) -> dict:
        """Publish one immutable version. Raises ConflictError if it exists."""
        record = make_definition_version_record(
            population_id,
            str(definition_version),
            _canonical_definition(definition),
            reason=reason,
            created_by=created_by,
            supersedes_version=supersedes_version,
        )
        existing = await self.find_by_id(record["id"])
        if existing is not None:
            raise ConflictError(
                f"Definition version {definition_version!r} for population "
                f"{population_id!r} already exists and is immutable"
            )
        return await self.insert(record["id"], record)

    async def history(self, population_id: str) -> list[dict]:
        """Definition versions oldest -> newest (version order, not write order)."""
        rows = await self.find_many(
            filters={"population_id": population_id}, limit=10000
        )
        return sorted(rows, key=lambda r: int(r.get("definition_version") or 0))

    async def latest(self, population_id: str) -> Optional[dict]:
        history = await self.history(population_id)
        return history[-1] if history else None


class PopulationRepository(BaseRepository):
    """Stores population objects (segments, cohorts, clusters, communities)."""

    def __init__(self) -> None:
        super().__init__("populations")

    async def create_population(
        self,
        name: str,
        population_type: PopulationType,
        description: str = "",
        definition: Optional[dict] = None,
        source_tag: str = "",
        tenant_id: str = "",
        metadata: Optional[dict] = None,
        consent_purpose: str = "analytics",
    ) -> dict:
        record = make_population_record(
            name=name,
            population_type=population_type,
            description=description,
            definition=definition,
            source_tag=source_tag,
            tenant_id=tenant_id,
            metadata=metadata,
            consent_purpose=consent_purpose,
        )
        result = await self.insert(record["id"], record)
        # Seed the immutable v1 definition contract (population360 P3.2) so every
        # population has a versioned definition from birth.
        await definition_repo.record(
            result["id"],
            "1",
            result.get("definition") or {},
            reason="initial definition",
            created_by="population_api",
        )
        metrics.increment("population_created", labels={"type": population_type.value})
        logger.info(f"Population created: {name} ({population_type.value})")
        return result

    async def revise_definition(
        self,
        population: dict,
        new_definition: Optional[dict],
        *,
        reason: str,
        created_by: str = "population_api",
    ) -> tuple[dict, dict]:
        """Publish a NEW immutable definition version (P3.2, governed).

        A definition is a versioned contract. ``revise_definition`` never edits
        a definition in place: it appends an immutable version (oldest -> newest
        in the ``population_definition_versions`` ledger) and advances the
        population row's current-definition projection to it, with a documented
        transition ``reason``. It refuses a *no-op* revision (a version bump to
        identical content would be a silent redefinition of nothing).

        Returns ``(updated_population, version_record)``.
        """
        population_id = population["id"]
        incoming = _canonical_definition(new_definition)

        if _definitions_equal(incoming, population.get("definition")):
            raise BadRequestError(
                "Definition is unchanged; refusing a no-op revision "
                "(a version bump to identical content would not be an honest transition)"
            )

        latest = await definition_repo.latest(population_id)
        next_version = str((int((latest or {}).get("definition_version") or 0)) + 1)
        version_record = await definition_repo.record(
            population_id,
            next_version,
            incoming,
            reason=reason,
            created_by=created_by,
            supersedes_version=str(
                (latest or {}).get("definition_version") or "1"
            ),
        )

        updated = await self.update(population_id, {
            "definition": incoming,
            "definition_version": next_version,
            "updated_at": utc_now().isoformat(),
        })
        metrics.increment(
            "population_definition_revised",
            labels={"type": population.get("population_type", "")},
        )
        return updated, version_record

    async def query_populations(
        self,
        tenant_id: str,
        population_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        filters: dict = {"tenant_id": tenant_id}
        if population_type:
            filters["population_type"] = population_type
        return await self.find_many(filters=filters, limit=limit)


def _membership_is_active(row: dict) -> bool:
    """A materialised membership row is active unless it says otherwise.

    Governed rows carry ``membership_state`` (P3.1); pre-governance legacy rows
    carry only ``status="active"`` and are treated as active.
    """
    state = row.get("membership_state") or row.get("status") or MembershipState.ACTIVE.value
    return state == MembershipState.ACTIVE.value


class MembershipRepository(BaseRepository):
    """Materialised population memberships with evidence and provenance.

    Since population360 P3.1 the authoritative membership fact is the governed
    ``MEMBER_OF`` graph edge; this table is the current-state materialisation
    the governed write path maintains (leaves transition state, never delete).
    Read helpers therefore surface *active* memberships by default.
    """

    def __init__(self) -> None:
        super().__init__("population_memberships")

    async def add_member(
        self,
        population_id: str,
        entity_id: str,
        entity_type: str = "user",
        basis: MembershipBasis = MembershipBasis.RULE,
        confidence: float = 1.0,
        reason: str = "",
        source_tag: str = "",
        tenant_id: str = "",
    ) -> dict:
        record = make_membership_record(
            population_id=population_id,
            entity_id=entity_id,
            entity_type=entity_type,
            basis=basis,
            confidence=confidence,
            reason=reason,
            source_tag=source_tag,
            tenant_id=tenant_id,
        )
        # Idempotent: update if exists
        existing = await self.find_by_id(record["id"])
        if existing:
            return await self.update(record["id"], {
                "confidence": confidence,
                "reason": reason,
                "source_tag": source_tag,
                "updated_at": utc_now().isoformat(),
            })
        return await self.insert(record["id"], record)

    async def add_members_batch(
        self,
        population_id: str,
        entity_ids: list[str],
        entity_type: str = "user",
        basis: MembershipBasis = MembershipBasis.RULE,
        confidence: float = 1.0,
        reason: str = "",
        source_tag: str = "",
        tenant_id: str = "",
    ) -> int:
        count = 0
        for eid in entity_ids:
            await self.add_member(
                population_id=population_id,
                entity_id=eid,
                entity_type=entity_type,
                basis=basis,
                confidence=confidence,
                reason=reason,
                source_tag=source_tag,
                tenant_id=tenant_id,
            )
            count += 1
        return count

    async def get_members(
        self,
        population_id: str,
        limit: int = 100,
        min_confidence: float = 0.0,
        include_inactive: bool = False,
    ) -> list[dict]:
        members = await self.find_many(
            filters={"population_id": population_id}, limit=limit
        )
        if not include_inactive:
            members = [m for m in members if _membership_is_active(m)]
        if min_confidence > 0:
            members = [m for m in members if m.get("confidence", 0) >= min_confidence]
        return members

    async def count_active_members(self, population_id: str) -> int:
        """Count *active* memberships (governed materialisation)."""
        rows = await self.find_many(
            filters={"population_id": population_id}, limit=10000
        )
        return sum(1 for r in rows if _membership_is_active(r))

    async def get_populations_for_entity(self, entity_id: str) -> list[dict]:
        """Get all populations an entity *actively* belongs to."""
        rows = await self.find_many(filters={"entity_id": entity_id}, limit=100)
        return [r for r in rows if _membership_is_active(r)]

    async def active_memberships_for_subject(
        self, tenant_id: str, entity_id: str
    ) -> list[dict]:
        """Active membership rows for one subject, tenant-scoped.

        Used by the population DSR-erasure plane (population360 P3.3) so a data
        subject's memberships are discovered without crossing tenants.
        """
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "entity_id": entity_id}, limit=10000
        )
        return [r for r in rows if _membership_is_active(r)]

    async def remove_member(self, population_id: str, entity_id: str) -> bool:
        import hashlib
        record_id = hashlib.sha256(f"{population_id}:{entity_id}".encode()).hexdigest()[:24]
        return await self.delete(record_id)


# Singletons
population_repo = PopulationRepository()
membership_repo = MembershipRepository()
definition_repo = PopulationDefinitionRepository()
