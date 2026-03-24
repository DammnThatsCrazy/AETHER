"""
Population Registry — Central store for all population objects and memberships.

Uses existing BaseRepository pattern (asyncpg in prod, in-memory in local).
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now, NotFoundError
from shared.logger.logger import get_logger, metrics
from services.population.models import (
    PopulationType, MembershipBasis,
    make_population_record, make_membership_record,
)

logger = get_logger("aether.population.registry")


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
    ) -> dict:
        record = make_population_record(
            name=name,
            population_type=population_type,
            description=description,
            definition=definition,
            source_tag=source_tag,
            tenant_id=tenant_id,
            metadata=metadata,
        )
        result = await self.insert(record["id"], record)
        metrics.increment("population_created", labels={"type": population_type.value})
        logger.info(f"Population created: {name} ({population_type.value})")
        return result

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


class MembershipRepository(BaseRepository):
    """Stores population memberships with evidence and provenance."""

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
    ) -> list[dict]:
        members = await self.find_many(
            filters={"population_id": population_id}, limit=limit
        )
        if min_confidence > 0:
            members = [m for m in members if m.get("confidence", 0) >= min_confidence]
        return members

    async def get_populations_for_entity(self, entity_id: str) -> list[dict]:
        """Get all populations an entity belongs to."""
        return await self.find_many(filters={"entity_id": entity_id}, limit=100)

    async def remove_member(self, population_id: str, entity_id: str) -> bool:
        import hashlib
        record_id = hashlib.sha256(f"{population_id}:{entity_id}".encode()).hexdigest()[:24]
        return await self.delete(record_id)


# Singletons
population_repo = PopulationRepository()
membership_repo = MembershipRepository()
