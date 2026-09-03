"""
Population membership governance (population360 P3.1).

Membership is a first-class **governed graph fact**: every join/leave is
written as a ``MEMBER_OF`` edge (entity -> population) through the canonical
:class:`~shared.graph.mutation_gateway.GraphMutationGateway` — never as a bare
table write. The gateway close-and-appends into the bitemporal ledger, so a
membership history is reconstructable and digest-verifiable like any other
canonical fact.

The population-membership table row is only the *materialized current state*
the governed path maintains after a successful edge write. Leaves are state
transitions (``membership_state=left`` + ``left_at``) — never a hard delete —
so the row stays a rebuildable materialization of the graph truth.

Consent/policy evaluation (P3.2) is applied by callers *before* invoking the
governor; this module is the write boundary, not the consent authority.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from shared.common.common import utc_now
from shared.graph.graph import Edge, EdgeType, GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, revocation_intent
from services.population.models import (
    MembershipBasis,
    MembershipState,
    make_membership_record,
)
from services.population.registry import (
    MembershipRepository,
    PopulationRepository,
    membership_repo,
    population_repo,
)

MEMBER_EDGE_ACTOR = "population_api"
MEMBER_EDGE_ROLE = "member"


def _membership_row_id(population_id: str, entity_id: str) -> str:
    return hashlib.sha256(f"{population_id}:{entity_id}".encode()).hexdigest()[:24]


class PopulationMembershipGovernor:
    """Governed write boundary for population membership.

    Mirrors the ``services/entities`` ``MEMBER_OF`` write pattern (the
    production template): an edge is passed through the gateway unchanged in
    ``off`` mode and, in ``shadow`` / ``enforce`` mode, is canonicalised onto
    the bitemporal ledger with full provenance. The population table row is
    materialised only after the edge write is applied.
    """

    def __init__(
        self,
        graph_client: GraphClient,
        population_repository: Optional[PopulationRepository] = None,
        membership_repository: Optional[MembershipRepository] = None,
    ) -> None:
        self._graph_client = graph_client
        self._populations = population_repository or population_repo
        self._memberships = membership_repository or membership_repo
        self._gateway = GraphMutationGateway(graph_client=graph_client)

    # ── writes ────────────────────────────────────────────────────────────────

    async def add_membership(
        self,
        *,
        population: dict,
        entity_id: str,
        entity_type: str = "user",
        basis: MembershipBasis = MembershipBasis.RULE,
        confidence: float = 1.0,
        reason: str = "",
        source_tag: str = "",
        tenant_id: str,
        evidence_refs: Optional[list[str]] = None,
        source_event_id: Optional[str] = None,
        actor_id: str = MEMBER_EDGE_ACTOR,
    ) -> dict:
        """Join ``entity_id`` to ``population`` as a governed ``MEMBER_OF`` edge.

        Returns the materialised membership row. Re-joining an active member is
        idempotent (the gateway dedups an identical edge write); re-joining a
        member who left starts a new membership episode on the ledger.
        """
        population_id = population["id"]
        definition_version = str(population.get("definition_version") or "1")
        evidence_refs = evidence_refs or []

        outcome = await self._gateway.apply(
            edge_intent(
                Edge(
                    edge_type=EdgeType.MEMBER_OF,
                    from_vertex_id=entity_id,
                    to_vertex_id=population_id,
                    properties={
                        "tenant_id": tenant_id,
                        "role": MEMBER_EDGE_ROLE,
                        "membership_state": MembershipState.ACTIVE.value,
                        "definition_version": definition_version,
                        "membership_basis": basis.value,
                        "population_type": population.get("population_type", ""),
                        "confidence": str(confidence),
                        "reason": reason,
                        "source_tag": source_tag,
                        "evidence_refs": list(evidence_refs),
                    },
                ),
                operation="edge_created",
                tenant_id=tenant_id,
                actor_kind="human",
                actor_id=actor_id,
                subject_kind="entity",
                subject_id=entity_id,
                confidence=confidence,
                evidence_refs=evidence_refs,
                source_event_id=source_event_id,
            )
        )

        return await self._materialise_join(
            population_id=population_id,
            entity_id=entity_id,
            entity_type=entity_type,
            basis=basis,
            confidence=confidence,
            reason=reason,
            source_tag=source_tag,
            tenant_id=tenant_id,
            definition_version=definition_version,
            evidence_refs=evidence_refs,
            outcome_applied=outcome.applied,
        )

    async def remove_membership(
        self,
        *,
        population: dict,
        entity_id: str,
        reason: str = "membership_left",
        tenant_id: str,
        actor_id: str = MEMBER_EDGE_ACTOR,
    ) -> dict:
        """Leave ``entity_id`` from ``population`` (governed soft-revoke).

        Revokes the active ``MEMBER_OF`` edge (``edge_expired`` — never a hard
        delete) and transitions the materialised row to ``membership_state=
        left``. Returns the materialised row (still present, state ``left``).
        """
        population_id = population["id"]
        now = utc_now().isoformat()

        await self._gateway.apply(
            revocation_intent(
                from_vertex_id=entity_id,
                to_vertex_id=population_id,
                edge_type=EdgeType.MEMBER_OF,
                reason=reason,
                tenant_id=tenant_id,
                operation="edge_expired",
                actor_kind="human",
                actor_id=actor_id,
                subject_kind="entity",
                subject_id=entity_id,
                reason_code=reason,
            )
        )

        row_id = _membership_row_id(population_id, entity_id)
        existing = await self._memberships.find_by_id(row_id)
        if existing is None:
            return {}
        updated = {
            **existing,
            "status": MembershipState.LEFT.value,
            "membership_state": MembershipState.LEFT.value,
            "left_at": now,
            "leave_reason": reason,
            "updated_at": now,
        }
        return await self._memberships.update(row_id, updated)

    # ── materialisation ───────────────────────────────────────────────────────

    async def _materialise_join(
        self,
        *,
        population_id: str,
        entity_id: str,
        entity_type: str,
        basis: MembershipBasis,
        confidence: float,
        reason: str,
        source_tag: str,
        tenant_id: str,
        definition_version: str,
        evidence_refs: list[str],
        outcome_applied: bool,
    ) -> dict:
        row_id = _membership_row_id(population_id, entity_id)
        existing = await self._memberships.find_by_id(row_id)
        now = utc_now().isoformat()

        if existing is None:
            row = make_membership_record(
                population_id=population_id,
                entity_id=entity_id,
                entity_type=entity_type,
                basis=basis,
                confidence=confidence,
                reason=reason,
                source_tag=source_tag,
                tenant_id=tenant_id,
                membership_state=MembershipState.ACTIVE.value,
                definition_version=definition_version,
                evidence_refs=evidence_refs,
            )
            return await self._memberships.insert(row_id, row)

        # Reactivation: a member who left/expired is joining again — the table
        # row is the current-state materialisation, so reset to active.
        was_inactive = existing.get("membership_state") != MembershipState.ACTIVE.value
        updated = {
            **existing,
            "entity_type": entity_type,
            "basis": basis.value,
            "confidence": confidence,
            "reason": reason,
            "source_tag": source_tag,
            "membership_state": MembershipState.ACTIVE.value,
            "status": MembershipState.ACTIVE.value,
            "definition_version": definition_version,
            "evidence_refs": evidence_refs,
            "updated_at": now,
        }
        if was_inactive:
            updated["joined_at"] = now
            updated["left_at"] = ""
            updated["leave_reason"] = ""
        return await self._memberships.update(row_id, updated)


__all__ = [
    "PopulationMembershipGovernor",
    "MEMBER_EDGE_ACTOR",
    "MEMBER_EDGE_ROLE",
    "_membership_row_id",
]
