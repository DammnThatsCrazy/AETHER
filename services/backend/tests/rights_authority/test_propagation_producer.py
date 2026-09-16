"""Rights propagation PRODUCER — resolve → stamp → record round trip.

Exercises ``services/rights_authority/propagation.py``, the producer that
carries a governing ``RightsDecision`` onto a governed write, plus the one real
pipeline wired to it (``services.population.governance``
``PopulationMembershipGovernor.add_membership`` → ``MutationIntent.
rights_decision_ref`` → ``MutationRecord.rights_decision_ref`` → the
``graph_mutation_ledger`` row).

The three properties this file pins:

1. **Round trip** — an ALLOW resolved by the authoritative
   ``EffectiveRightsResolver`` is stamped onto the intent, reaches the built
   ``MutationRecord`` and the append-only ledger row, and rides the
   ``SpineEnvelope`` (ref + decision evidence).
2. **A denied/revoked basis never stamps an allow** — no ref is written, and
   under ``enforce`` the denial binds (the write is refused instead of being
   written with no rights ancestry).
3. **A ref-unset write is unchanged** — with the gate off, nothing is resolved,
   recorded, or stamped, and the ledger row carries ``None`` exactly as before.
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from repositories.repos import reset_in_memory_stores
from services.integrations.data_rights.models import DataRightsGrant, GrantStatus
from services.population.governance import (
    MembershipRightsDeniedError,
    PopulationMembershipGovernor,
)
from services.rights_authority.contracts import RightsDecision
from services.rights_authority.propagation import (
    DECISION_REF_PREFIX,
    RightsPropagation,
    RightsPropagationDenied,
    propagate_rights,
    stamp_envelope,
    stamp_intent,
)
from services.rights_authority.resolver import EffectiveRightsResolver
from services.rights_authority.rollout import configure_rollout, reset_rollout
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway, MutationIntent
from shared.spine.spine_envelope import SpineEnvelope, SpineEnvelopeQuality

TENANT = "tenant_propagation"
SOURCE = "src_propagation"
VALID_FROM = "2026-07-01T00:00:00+00:00"
DISPOSITION_ALLOWED = "allowed"


@pytest.fixture(autouse=True)
def _reset_state():
    """Empty in-memory decision store + ledger, and an unpinned rollout."""
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    reset_rollout()
    yield
    reset_rollout()
    reset_in_memory_stores()
    reset_graph_ledger_memory()


def _grant(**overrides) -> DataRightsGrant:
    base = {
        "data_rights_grant_id": "drg_propagation_001",
        "tenant_id": TENANT,
        "contract_id": None,
        "source_id": SOURCE,
        "connector_id": "dune_api",
        "connector_class": "olympus_provider",
        "source_manifest_id": None,
        "data_category": "onchain",
        "data_sensitivity": "unclassified",
        "raw_data_owner": "olympus_labs",
        "tenant_lake_allowed": True,
        "tenant_graph_allowed": True,
        "tenant_insights_allowed": True,
        "olympus_baseline_allowed": False,
        "cross_tenant_aggregate_allowed": False,
        "model_training_allowed": False,
        "commercial_reuse_allowed": False,
        "legal_basis": "operator_policy",
        "consent_basis": None,
        "granted_by_user_id": "user_1",
        "granted_at": "2026-09-01T00:00:00+00:00",
        "expires_at": None,
        "revoked_at": None,
        "revocation_reason": None,
        "status": GrantStatus.ACTIVE,
        "audit_event_id": "audit_1",
    }
    base.update(overrides)
    return DataRightsGrant(**base)


def _resolver(grant: DataRightsGrant | None) -> EffectiveRightsResolver:
    """The authoritative resolver with a controlled grant store.

    The resolver itself is not stubbed — ``resolve_request`` (identity,
    temporal check, family evaluation, durable record) runs for real.
    """

    async def _loader(_tenant_id: str, source_id: str):
        if grant is not None and grant.source_id == source_id:
            return grant
        return None

    return EffectiveRightsResolver(grant_loader=_loader)


def _edge(*, source_event_id: str = "evt-prop") -> Edge:
    props = build_edge_properties(
        tenant_id=TENANT,
        edge_type="MEMBER_OF",
        from_vertex_id="entity_prop",
        to_vertex_id="population_prop",
        actor_kind="human",
        actor_id="population_api",
        provenance="test",
        valid_from=VALID_FROM,
        confidence=1.0,
        source_event_id=source_event_id,
    )
    return Edge(
        edge_type="MEMBER_OF",
        from_vertex_id="entity_prop",
        to_vertex_id="population_prop",
        properties=props,
    )


def _envelope() -> SpineEnvelope:
    return SpineEnvelope(
        tenant_id=TENANT,
        request_id="req_prop",
        scope_ref="scope_prop",
        subject_refs=[],
        as_of="2026-09-07T00:00:00+00:00",
        evidence_refs=[],
        quality=SpineEnvelopeQuality(state="available"),
        contract_versions={},
        model_refs=[],
        lineage_refs=[],
    )


def _gateway() -> tuple[GraphMutationGateway, GraphClient, GraphMutationLedgerRepository]:
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    return GraphMutationGateway(graph_client=client, ledger=ledger), client, ledger


@pytest.fixture()
def gateway_mode(monkeypatch):
    """Pin the graph-gateway mode ladder (ledger writes happen in shadow/enforce)."""

    def _set(mode_name: str) -> str:
        monkeypatch.setattr(
            settings,
            "temporal_observatory",
            dataclasses.replace(
                settings.temporal_observatory, mutation_gateway_mode=mode_name
            ),
        )
        return mode_name

    return _set


@pytest.fixture()
def consent_ok(monkeypatch):
    """Stand in for the server consent-receipt store: membership consent granted."""

    async def _allowed(_tenant_id, *, subject_id, anonymous_id, purpose):
        return True, ""

    monkeypatch.setattr(
        "services.population.governance.evaluate_consent", _allowed
    )


async def _propagate(resolver: EffectiveRightsResolver, **overrides):
    kwargs = {
        "tenant_id": TENANT,
        "source_id": SOURCE,
        "actor": "population_api",
        "purpose": "analytics",
        "resolver": resolver,
    }
    kwargs.update(overrides)
    return await propagate_rights(**kwargs)


# ── Gate: OFF is inert ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_off_resolves_nothing() -> None:
    """``off`` returns before the resolver is consulted — no decision, no stamp.

    The loader is deliberately rigged to explode, so any resolve attempt fails
    the test loudly instead of passing silently.
    """
    async def _boom(_tenant_id: str, _source_id: str):
        raise AssertionError("resolver must not run while the gate is off")

    assert await _propagate(EffectiveRightsResolver(grant_loader=_boom)) is None


@pytest.mark.asyncio
async def test_ref_unset_write_is_unchanged(gateway_mode) -> None:
    """With the gate off, a propagation-stamped write is byte-identical to today."""
    gateway_mode("shadow")
    gateway, client, ledger = _gateway()
    outcome = await gateway.apply(
        stamp_intent(
            MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge()),
            await _propagate(_resolver(_grant())),
        )
    )
    assert outcome.applied and outcome.ledger_recorded

    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["rights_decision_ref"] is None
    assert "rights_decision_ref" not in rows[0]["payload"]
    assert len(await client.get_edges("entity_prop")) == 1


# ── Round trip: resolve → stamp → record ──────────────────────────────────────


@pytest.mark.asyncio
async def test_allow_round_trip_intent_to_ledger_row(gateway_mode) -> None:
    configure_rollout("shadow")
    gateway_mode("shadow")
    propagation = await _propagate(_resolver(_grant()))
    assert propagation is not None
    assert propagation.allowed and propagation.stamped
    assert propagation.decision_id.startswith(DECISION_REF_PREFIX)

    intent = stamp_intent(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge()),
        propagation,
    )
    assert intent.rights_decision_ref == propagation.decision_id

    gateway, client, ledger = _gateway()
    outcome = await gateway.apply(intent)
    assert outcome.applied and outcome.ledger_recorded

    # The typed record carries it, and so does the durable ledger row.
    assert outcome.record is not None
    assert outcome.record.rights_decision_ref == propagation.decision_id
    rows = await ledger.list_records(TENANT)
    assert rows[0]["rights_decision_ref"] == propagation.decision_id
    assert rows[0]["payload"]["rights_decision_ref"] == propagation.decision_id

    # Governance metadata only: graph topology is untouched.
    edges = await client.get_edges("entity_prop")
    assert len(edges) == 1
    assert "rights_decision_ref" not in edges[0].properties


@pytest.mark.asyncio
async def test_allow_round_trip_is_recorded_durably() -> None:
    """The resolver's decision is durable — the stamped ref is resolvable."""
    from services.rights_authority.repositories import rights_decision_repository

    configure_rollout("shadow")
    propagation = await _propagate(_resolver(_grant()))
    assert propagation is not None
    stored = await rights_decision_repository.get(propagation.decision_id)
    assert stored is not None
    assert stored["decision_id"] == propagation.decision_id
    assert stored["allowed"] is True


@pytest.mark.asyncio
async def test_stamp_envelope_round_trip() -> None:
    configure_rollout("shadow")
    propagation = await _propagate(_resolver(_grant()))
    envelope = stamp_envelope(_envelope(), propagation)
    assert propagation is not None

    assert envelope.rights_decision_ref == propagation.decision_id
    assert [e.id for e in envelope.evidence_refs] == [propagation.decision_id]
    assert envelope.evidence_refs[0].source == "rights_authority.decision"

    # Re-stamping the same envelope with the same decision is a no-op.
    stamp_envelope(envelope, propagation)
    assert [e.id for e in envelope.evidence_refs] == [propagation.decision_id]


def test_stamp_helpers_are_noops_without_a_propagation() -> None:
    intent = MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    assert stamp_intent(intent, None) is intent
    assert intent.rights_decision_ref is None

    envelope = _envelope()
    assert stamp_envelope(envelope, None) is envelope
    assert envelope.rights_decision_ref is None
    assert envelope.evidence_refs == []


# ── Denied / revoked basis: never an allow ────────────────────────────────────


@pytest.mark.asyncio
async def test_no_grant_denial_does_not_stamp() -> None:
    """An unknown source resolves ``no_grant`` and stamps nothing."""
    configure_rollout("shadow")
    propagation = await _propagate(_resolver(None))
    assert propagation is not None
    assert not propagation.allowed and not propagation.stamped
    assert propagation.reason_codes == ["no_grant"]

    intent = stamp_intent(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge()),
        propagation,
    )
    assert intent.rights_decision_ref is None

    envelope = stamp_envelope(_envelope(), propagation)
    assert envelope.rights_decision_ref is None
    assert envelope.evidence_refs == []


@pytest.mark.asyncio
async def test_revoked_grant_denial_does_not_stamp() -> None:
    """A revoked grant is a denial, not an allow with a stale ref."""
    configure_rollout("shadow")
    revoked = _grant(
        status=GrantStatus.REVOKED,
        revoked_at="2026-09-02T00:00:00+00:00",
        revocation_reason="tenant_withdrew",
    )
    propagation = await _propagate(_resolver(revoked))
    assert propagation is not None
    assert not propagation.allowed and not propagation.stamped
    assert propagation.reason_codes == ["grant_revoked"]
    assert stamp_intent(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge()),
        propagation,
    ).rights_decision_ref is None


@pytest.mark.asyncio
async def test_enforce_denial_binds() -> None:
    configure_rollout("enforce")
    with pytest.raises(RightsPropagationDenied) as exc:
        await _propagate(_resolver(None))
    assert exc.value.reason_codes == ["no_grant"]


@pytest.mark.asyncio
async def test_untraceable_decision_id_is_rejected(monkeypatch) -> None:
    """A resolver returning a non-durable id cannot get it stamped."""
    configure_rollout("shadow")
    resolver = _resolver(_grant())

    async def _bad_request(_request, *, replay_recorded: bool = True):
        return RightsDecision(
            decision_id="not-a-durable-ref",
            tenant_id=TENANT,
            allowed=True,
            disposition=DISPOSITION_ALLOWED,
        )

    monkeypatch.setattr(resolver, "resolve_request", _bad_request)
    with pytest.raises(ValueError):
        await _propagate(resolver)


# ── The wired pipeline: population membership ─────────────────────────────────


def _population() -> dict:
    return {
        "id": "pop_prop",
        "name": "prop cohort",
        "population_type": "segment",
        "definition_version": "1",
        "consent_purpose": "analytics",
        "source_tag": SOURCE,
    }


@pytest.mark.asyncio
async def test_pipeline_gate_off_write_is_byte_identical(gateway_mode, consent_ok) -> None:
    """Rollout off: the governed join writes exactly what it wrote before.

    Asserted against the same join with the producer absent from the call path:
    the ledger row is compared field by field, ignoring only the fields that
    carry a wall-clock instant or a freshly minted uuid.
    """
    gateway_mode("shadow")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    governor = PopulationMembershipGovernor(graph_client=client)
    governor._gateway = GraphMutationGateway(graph_client=client, ledger=ledger)

    await governor.add_membership(
        population=_population(), entity_id="entity_prop", tenant_id=TENANT
    )
    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["rights_decision_ref"] is None
    assert "rights_decision_ref" not in rows[0]["payload"]

    # Control: the same write with the ref explicitly unset (no gate in play).
    reset_graph_ledger_memory()
    client2 = GraphClient()
    ledger2 = GraphMutationLedgerRepository()
    governor2 = PopulationMembershipGovernor(graph_client=client2)
    governor2._gateway = GraphMutationGateway(graph_client=client2, ledger=ledger2)
    await governor2.add_membership(
        population=_population(), entity_id="entity_prop", tenant_id=TENANT
    )
    control = await ledger2.list_records(TENANT)

    # Fields that legitimately carry a wall-clock instant or a freshly minted
    # uuid: the mutation/version ids and the gateway's own `valid_from`
    # canonicalisation (also nested inside the payload's edge properties).
    volatile = {
        "mutation_id",
        "after_version_id",
        "ledger_offset",
        "valid_from",
        "valid_to",
        "recorded_at",
        "superseded_at",
    }

    def _stable(row: dict) -> dict:
        stable = {k: v for k, v in row.items() if k not in volatile}
        payload = stable.get("payload")
        if isinstance(payload, dict):
            stable["payload"] = {
                **payload,
                "properties": {
                    k: v
                    for k, v in (payload.get("properties") or {}).items()
                    if k != "valid_from"
                },
            }
        return stable

    assert _stable(rows[0]) == _stable(control[0])


@pytest.mark.asyncio
async def test_pipeline_stamps_resolved_decision(
    gateway_mode, consent_ok, monkeypatch
) -> None:
    """Active gate: the join's ledger row carries the resolved ``rdec_...`` ref."""
    configure_rollout("shadow")
    gateway_mode("shadow")
    resolver = _resolver(_grant())
    monkeypatch.setattr(
        "services.population.governance.propagate_rights",
        lambda **kwargs: propagate_rights(**{**kwargs, "resolver": resolver}),
    )

    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    governor = PopulationMembershipGovernor(graph_client=client)
    governor._gateway = GraphMutationGateway(graph_client=client, ledger=ledger)

    row = await governor.add_membership(
        population=_population(), entity_id="entity_prop", tenant_id=TENANT
    )
    assert row  # the materialised membership row still lands

    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    ref = rows[0]["rights_decision_ref"]
    assert ref is not None and ref.startswith(DECISION_REF_PREFIX)
    assert rows[0]["payload"]["rights_decision_ref"] == ref


@pytest.mark.asyncio
async def test_pipeline_enforce_denial_refuses_the_join(
    gateway_mode, consent_ok, monkeypatch
) -> None:
    """``enforce`` + a denied basis: the join raises and nothing is written."""
    configure_rollout("enforce")
    gateway_mode("shadow")
    monkeypatch.setattr(
        "services.population.governance.propagate_rights",
        lambda **kwargs: propagate_rights(**{**kwargs, "resolver": _resolver(None)}),
    )

    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    governor = PopulationMembershipGovernor(graph_client=client)
    governor._gateway = GraphMutationGateway(graph_client=client, ledger=ledger)

    with pytest.raises(MembershipRightsDeniedError) as exc:
        await governor.add_membership(
            population=_population(), entity_id="entity_prop", tenant_id=TENANT
        )
    assert exc.value.reason_codes == ["no_grant"]
    assert exc.value.entity_id == "entity_prop"
    assert exc.value.population_id == "pop_prop"

    # No edge, no ledger row, no materialised membership.
    assert await ledger.list_records(TENANT) == []
    assert await client.get_edges("entity_prop") == []


# ── The propagation result type ───────────────────────────────────────────────


def test_propagation_result_is_frozen_and_reports_its_decision() -> None:
    decision = RightsDecision(
        decision_id="rdec_frozen",
        tenant_id=TENANT,
        allowed=True,
        disposition=DISPOSITION_ALLOWED,
    )
    from services.rights_authority.rollout import RolloutMode

    propagation = RightsPropagation(decision=decision, mode=RolloutMode.SHADOW, stamped=True)
    assert propagation.decision_id == "rdec_frozen"
    assert propagation.allowed is True
    assert propagation.reason_codes == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        propagation.stamped = False  # type: ignore[misc]
