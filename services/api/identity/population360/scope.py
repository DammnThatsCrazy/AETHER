"""Tenant-verified current membership scope for population-backed 360 reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef


PopulationScopeState = Literal[
    "available", "empty", "unknown", "degraded", "truncated", "conflicted"
]


@dataclass(frozen=True)
class PopulationScopeRead:
    """Bounded current-membership result with source evidence and completeness."""

    tenant_id: str
    population_id: str
    state: PopulationScopeState
    entity_ids: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None

    @property
    def complete(self) -> bool:
        return self.state in {"available", "empty"}


class PopulationScopeReader(Protocol):
    """Read the current active members of one tenant-owned population."""

    async def resolve(
        self, tenant_id: str, population_id: str, *, limit: int
    ) -> PopulationScopeRead: ...


class RepositoryPopulationScopeReader:
    """Adapter over the existing population and membership registries."""

    async def resolve(
        self, tenant_id: str, population_id: str, *, limit: int
    ) -> PopulationScopeRead:
        try:
            from identity.population.registry import membership_repo, population_repo

            population = await population_repo.find_by_id(population_id)
            if (
                not isinstance(population, dict)
                or population.get("id") != population_id
                or population.get("tenant_id") != tenant_id
            ):
                return PopulationScopeRead(
                    tenant_id,
                    population_id,
                    "unknown",
                    reason="tenant_owned_population_not_found",
                )
            rows = await membership_repo.find_many(
                filters={"population_id": population_id}, limit=max(1, limit) + 1
            )
        except Exception as exc:  # noqa: BLE001 - membership authority stays explicit
            return PopulationScopeRead(
                tenant_id,
                population_id,
                "degraded",
                reason=f"population_membership_{type(exc).__name__}",
            )

        if not isinstance(rows, list):
            return PopulationScopeRead(
                tenant_id,
                population_id,
                "degraded",
                reason="population_membership_invalid_source_contract",
            )
        if len(rows) > max(1, limit):
            return PopulationScopeRead(
                tenant_id,
                population_id,
                "truncated",
                reason="population_membership_read_capped",
            )

        entity_ids: set[str] = set()
        population_evidence_id = population.get("id")
        if not isinstance(population_evidence_id, str) or not population_evidence_id.strip():
            return PopulationScopeRead(
                tenant_id,
                population_id,
                "conflicted",
                reason="population_identity_evidence_missing",
            )
        refs: list[EvidenceRef] = [
            EvidenceRef(
                id=population_evidence_id,
                type="entity",
                source="identity_populations",
                observedAt=(
                    population.get("updated_at")
                    if isinstance(population.get("updated_at"), str)
                    else population.get("created_at")
                    if isinstance(population.get("created_at"), str)
                    else None
                ),
                uri=f"store://populations/{population_evidence_id}",
            )
        ]
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("population_id") != population_id
            ):
                return PopulationScopeRead(
                    tenant_id,
                    population_id,
                    "conflicted",
                    reason="population_membership_scope_mismatch",
                )
            state = row.get("membership_state") or row.get("status") or "active"
            if state != "active":
                continue
            entity_id = row.get("entity_id")
            evidence_id = row.get("id")
            if (
                not isinstance(entity_id, str)
                or not entity_id.strip()
                or not isinstance(evidence_id, str)
                or not evidence_id.strip()
            ):
                return PopulationScopeRead(
                    tenant_id,
                    population_id,
                    "conflicted",
                    reason="population_membership_identity_or_evidence_missing",
                )
            entity_ids.add(entity_id)
            refs.append(
                EvidenceRef(
                    id=evidence_id,
                    type="entity",
                    source="identity_population_memberships",
                    observedAt=(
                        row.get("joined_at")
                        if isinstance(row.get("joined_at"), str)
                        else row.get("updated_at")
                        if isinstance(row.get("updated_at"), str)
                        else None
                    ),
                    uri=f"store://population_memberships/{evidence_id}",
                )
            )

        ordered_ids = tuple(sorted(entity_ids))
        return PopulationScopeRead(
            tenant_id,
            population_id,
            "available" if ordered_ids else "empty",
            entity_ids=ordered_ids,
            evidence_refs=tuple(refs),
        )


__all__ = [
    "PopulationScopeRead",
    "PopulationScopeReader",
    "PopulationScopeState",
    "RepositoryPopulationScopeReader",
]
