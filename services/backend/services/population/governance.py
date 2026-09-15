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

Consent/policy evaluation (P3.2) is applied at the write boundary itself,
server-authoritative (``services.consent.authority.evaluate_consent``) for the
member data subject under the population's declared ``consent_purpose`` —
fail-closed, never merely a tenant ``write`` permission. Joining is gated;
leaving is always honored (a subject may exit a cohort regardless of current
grant state), so a leave is never blocked by a revoked receipt.

Rights propagation (blueprint §11 / §17 Phase 3) rides the same boundary: a
join first asks the Rights Authority propagation producer
(``services.rights_authority.propagation.propagate_rights``) for the governing
``RightsDecision`` of writing this membership into the tenant graph, and stamps
the returned durable ``rdec_...`` id onto the ``MEMBER_OF`` intent. With
``RIGHTS_AUTHORITY_ROLLOUT`` unset/``off`` the producer returns ``None`` before
it touches the resolver, so the intent carries no ref and the write is
byte-identical to its pre-propagation behaviour. The producer is not a second
consent gate: ``assert_membership_allowed`` remains the authority on the member
data subject, and the rights gate is consulted after it.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from services.consent.authority import evaluate_consent
from services.rights_authority.propagation import (
    RightsPropagationDenied,
    propagate_rights,
    stamp_intent,
)
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
DEFAULT_CONSENT_PURPOSE = "analytics"


class MembershipConsentDeniedError(Exception):
    """A governed membership write was refused by server consent evaluation.

    Carries the stable ``REJECTION_CODES`` reason (e.g. ``consent_receipt_missing``,
    ``consent_revoked``) so callers can render a typed 403.
    """

    def __init__(self, reason_code: str, *, entity_id: str, purpose: str) -> None:
        super().__init__(f"Membership denied by consent: {reason_code}")
        self.reason_code = reason_code
        self.entity_id = entity_id
        self.purpose = purpose


class MembershipRightsDeniedError(Exception):
    """A governed membership write was refused by the rights-propagation gate.

    Raised only when the Rights Authority rollout is in ``enforce`` and the
    governing ``RightsDecision`` for this membership write is a denial — the
    propagation producer's :class:`RightsPropagationDenied` re-raised with the
    membership context (population/entity) a caller needs to render a typed
    refusal. It mirrors :class:`MembershipConsentDeniedError` deliberately: the
    rights gate sits beside the consent gate at the same write boundary.
    """

    def __init__(
        self,
        reason_codes: list[str],
        *,
        entity_id: str,
        population_id: str,
    ) -> None:
        reasons = "|".join(reason_codes) or "denied"
        super().__init__(f"Membership denied by rights authority: {reasons}")
        self.reason_codes = list(reason_codes)
        self.entity_id = entity_id
        self.population_id = population_id


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

    # ── consent ──────────────────────────────────────────────────────────────

    async def assert_membership_allowed(
        self,
        *,
        population: dict,
        entity_id: str,
        tenant_id: str,
    ) -> None:
        """Server-authoritative consent check for a membership write (P3.2).

        Joining an entity into a population processes that entity under the
        population's declared ``consent_purpose`` (default ``analytics``). The
        server consent-receipt store decides — absence is denial. Raises
        :class:`MembershipConsentDeniedError` with the stable reason code on any
        denial. Leaves are deliberately NOT gated: a subject may exit a cohort
        regardless of current grant state.
        """
        purpose = str(
            population.get("consent_purpose") or DEFAULT_CONSENT_PURPOSE
        ).strip() or DEFAULT_CONSENT_PURPOSE
        allowed, reason_code = await evaluate_consent(
            tenant_id,
            subject_id=entity_id,
            anonymous_id=None,
            purpose=purpose,
        )
        if not allowed:
            raise MembershipConsentDeniedError(
                reason_code or "consent_denied",
                entity_id=entity_id,
                purpose=purpose,
            )

    # ── rights propagation (blueprint §11 / §17 Phase 3) ─────────────────────

    async def resolve_membership_rights(
        self,
        *,
        population: dict,
        entity_id: str,
        tenant_id: str,
        actor_id: str,
    ):
        """Resolve the governing ``RightsDecision`` for one membership write.

        Returns the propagation result, or ``None`` when the Rights Authority
        rollout gate is off (nothing is resolved, recorded or stamped — the
        write is byte-identical to its pre-propagation behaviour).

        ``source_id`` is the population's DECLARED provenance
        (``population["source_tag"]``), falling back to the population's own id
        when it declares none. The request's ``source_tag`` metadata is
        deliberately NOT consulted: the rights question is a property of the
        governed object's declared ancestry, never of a caller-supplied string
        on the write being authorized. A source the grant store does not know
        resolves to a ``no_grant`` denial rather than an implicit allow — the
        correct fail-closed answer for a write whose data ancestry cannot be
        named.

        Under ``RIGHTS_AUTHORITY_ROLLOUT=enforce`` a denied decision binds and
        is re-raised as :class:`MembershipRightsDeniedError`; in ``shadow`` /
        ``warn`` the denial is returned for the caller to surface without
        blocking.
        """
        population_id = str(population.get("id") or "")
        purpose = str(
            population.get("consent_purpose") or DEFAULT_CONSENT_PURPOSE
        ).strip() or DEFAULT_CONSENT_PURPOSE
        source_id = str(population.get("source_tag") or population_id)
        try:
            return await propagate_rights(
                tenant_id=tenant_id,
                source_id=source_id,
                actor=actor_id,
                actor_role=MEMBER_EDGE_ROLE,
                purpose=purpose,
                artifact_ref=f"population:{population_id}",
                artifact_class=str(population.get("population_type") or ""),
                subject_ref=entity_id,
            )
        except RightsPropagationDenied as exc:
            raise MembershipRightsDeniedError(
                exc.reason_codes,
                entity_id=entity_id,
                population_id=population_id,
            ) from exc

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

        The write is consent-gated (P3.2): :meth:`assert_membership_allowed` is
        evaluated first and any denial raises before an edge or row is touched.
        Returns the materialised membership row. Re-joining an active member is
        idempotent (the gateway dedups an identical edge write); re-joining a
        member who left starts a new membership episode on the ledger.

        The write also carries its governing rights decision when the Rights
        Authority rollout gate is active: :meth:`resolve_membership_rights` runs
        the authoritative resolver and its durable ``rdec_...`` id is stamped
        onto the intent's ``rights_decision_ref``. With the gate off (the
        default) no ref is resolved or stamped.
        """
        await self.assert_membership_allowed(
            population=population, entity_id=entity_id, tenant_id=tenant_id
        )
        population_id = population["id"]
        definition_version = str(population.get("definition_version") or "1")
        evidence_refs = evidence_refs or []

        propagation = await self.resolve_membership_rights(
            population=population,
            entity_id=entity_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )

        outcome = await self._gateway.apply(
            stamp_intent(
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
                ),
                propagation,
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
    "DEFAULT_CONSENT_PURPOSE",
    "MembershipConsentDeniedError",
    "MembershipRightsDeniedError",
    "PopulationMembershipGovernor",
    "MEMBER_EDGE_ACTOR",
    "MEMBER_EDGE_ROLE",
    "_membership_row_id",
]
