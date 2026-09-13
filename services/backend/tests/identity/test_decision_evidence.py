"""Tests for identity decision evidence (prompt §3.3).

Covers:
  * the evidence service (record_decision / list_for_entity) + tenant isolation
  * MergeDecision -> DecisionType mapping (incl. fail-closed coercion)
  * evidence is recorded as a side effect of a real resolution, additively
"""
from __future__ import annotations

import os
import sys

import pytest

# Make backend packages importable when this suite is run in isolation.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.decision_evidence import (  # noqa: E402
    DecisionType,
    IdentityDecisionEvidenceRepository,
    IdentityDecisionEvidenceService,
    coerce_decision_type,
    decision_type_from_merge_decision,
    hash_consent_snapshot,
)
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import ConfidenceTier, MergeDecision  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402

TENANT = "tenant_evidence"
OTHER_TENANT = "tenant_other"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


def _build_resolver() -> IdentityResolutionService:
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )


# ── DecisionType mapping ────────────────────────────────────────────────────────

def test_merge_decision_maps_to_decision_type():
    assert decision_type_from_merge_decision(MergeDecision.CREATE) == DecisionType.AUTO_LINK
    assert decision_type_from_merge_decision(MergeDecision.LINK) == DecisionType.AUTO_LINK
    assert decision_type_from_merge_decision(MergeDecision.MERGE) == DecisionType.MERGE
    assert decision_type_from_merge_decision(MergeDecision.REJECT) == DecisionType.REJECT
    assert decision_type_from_merge_decision(MergeDecision.BLOCKED) == DecisionType.REJECT


def test_candidate_maps_to_conflict_when_conflicting():
    assert (
        decision_type_from_merge_decision(MergeDecision.CANDIDATE, has_conflict=False)
        == DecisionType.CANDIDATE_LINK
    )
    assert (
        decision_type_from_merge_decision(MergeDecision.CANDIDATE, has_conflict=True)
        == DecisionType.CONFLICT
    )


def test_coerce_decision_type_is_fail_closed():
    assert coerce_decision_type("merge") == DecisionType.MERGE
    assert coerce_decision_type(DecisionType.SPLIT) == DecisionType.SPLIT
    # Unknown -> CONFLICT (routed to review, never silently benign).
    assert coerce_decision_type("banana") == DecisionType.CONFLICT


def test_consent_snapshot_hash_is_deterministic():
    a = hash_consent_snapshot({"purpose": "analytics", "granted": True})
    b = hash_consent_snapshot({"granted": True, "purpose": "analytics"})
    assert a == b and a != ""
    assert hash_consent_snapshot(None) == ""


# ── Evidence service: record + list + tenant isolation ─────────────────────────

@pytest.mark.asyncio
async def test_record_decision_persists_and_lists():
    svc = IdentityDecisionEvidenceService()
    ev = await svc.record_decision(
        tenant_id=TENANT,
        entity_id="entity_1",
        decision_type="auto_link",
        signals_used=["user_id"],
        signals_excluded=["email_hash"],
        source_events=["evt_1"],
        source_connectors=["sdk_event"],
        confidence_score=0.95,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        policy_decision_id="audit_1",
    )
    assert ev.decision_type == DecisionType.AUTO_LINK
    assert ev.review_status == "auto"

    rows = await svc.list_for_entity(TENANT, "entity_1")
    assert len(rows) == 1
    row = rows[0]
    assert row["decision_type"] == "auto_link"
    assert row["signals_used"] == ["user_id"]
    assert row["signals_excluded"] == ["email_hash"]
    assert row["confidence_tier"] == "deterministic"
    assert row["policy_decision_id"] == "audit_1"


@pytest.mark.asyncio
async def test_evidence_is_tenant_isolated():
    svc = IdentityDecisionEvidenceService()
    await svc.record_decision(
        tenant_id=TENANT, entity_id="shared_entity", decision_type="merge",
    )
    await svc.record_decision(
        tenant_id=OTHER_TENANT, entity_id="shared_entity", decision_type="reject",
    )

    mine = await svc.list_for_entity(TENANT, "shared_entity")
    theirs = await svc.list_for_entity(OTHER_TENANT, "shared_entity")
    assert len(mine) == 1
    assert len(theirs) == 1
    assert mine[0]["decision_type"] == "merge"
    assert theirs[0]["decision_type"] == "reject"

    # Cross-tenant point read is also scoped.
    repo = IdentityDecisionEvidenceRepository()
    only_id = mine[0]["decision_id"]
    assert await repo.get_for_tenant(TENANT, only_id) is not None
    assert await repo.get_for_tenant(OTHER_TENANT, only_id) is None


@pytest.mark.asyncio
async def test_unknown_decision_type_recorded_as_conflict():
    svc = IdentityDecisionEvidenceService()
    ev = await svc.record_decision(
        tenant_id=TENANT, entity_id="entity_x", decision_type="not_a_real_type",
    )
    assert ev.decision_type == DecisionType.CONFLICT
    assert ev.review_status == "pending"


# ── Evidence recorded from a real resolution (additive) ────────────────────────
#
# NOTE: the resolver's decision surface is exercised as-is; these tests do not
# assert a particular MergeDecision (that is owned by the policy/confidence
# tests). They assert that evidence is recorded additively and that the recorded
# decision_type faithfully mirrors whatever decision the resolver returned.

@pytest.mark.asyncio
async def test_resolution_records_evidence_additively():
    resolver = _build_resolver()
    decision = await resolver.resolve_event(
        {"event_id": "evt_new", "user_id": "user_abc"}, TENANT,
    )
    assert decision.canonical_entity_id

    svc = IdentityDecisionEvidenceService()
    rows = await svc.list_for_entity(TENANT, decision.canonical_entity_id)
    assert len(rows) == 1
    ev = rows[0]
    # The recorded decision_type mirrors the actual policy decision, and the
    # audit record is captured as the policy decision reference.
    expected_type = decision_type_from_merge_decision(decision.decision).value
    assert ev["decision_type"] == expected_type
    assert ev["source_events"] == ["evt_new"]
    assert ev["policy_decision_id"] == decision.audit_id
    assert ev["confidence_tier"] == decision.confidence_tier.value
    assert ev["decision_id"] == ev["id"]


@pytest.mark.asyncio
async def test_resolution_evidence_is_tenant_isolated():
    resolver = _build_resolver()
    d_a = await resolver.resolve_event(
        {"event_id": "evt_a", "user_id": "user_x"}, TENANT,
    )
    d_b = await resolver.resolve_event(
        {"event_id": "evt_b", "user_id": "user_y"}, OTHER_TENANT,
    )
    svc = IdentityDecisionEvidenceService()
    rows_a = await svc.list_for_entity(TENANT, d_a.canonical_entity_id)
    rows_b = await svc.list_for_entity(OTHER_TENANT, d_b.canonical_entity_id)
    assert len(rows_a) == 1 and rows_a[0]["tenant_id"] == TENANT
    assert len(rows_b) == 1 and rows_b[0]["tenant_id"] == OTHER_TENANT
    # An entity id is never visible across tenants.
    assert await svc.list_for_entity(OTHER_TENANT, d_a.canonical_entity_id) == []


@pytest.mark.asyncio
async def test_evidence_failure_never_breaks_resolution():
    control = _build_resolver()
    control_decision = await control.resolve_event(
        {"event_id": "evt_ctrl", "user_id": "user_ctrl"}, TENANT,
    )

    resolver = _build_resolver()

    class _Boom:
        async def record_decision(self, **_kwargs):
            raise RuntimeError("evidence backend down")

    # Inject a failing recorder — resolution must still complete normally and
    # must NOT fall through to the resolver's generic internal-error handler.
    resolver._decision_evidence = _Boom()  # type: ignore[assignment]
    decision = await resolver.resolve_event(
        {"event_id": "evt_boom", "user_id": "user_ctrl"}, TENANT,
    )
    assert decision.canonical_entity_id
    assert "internal_error" not in decision.reason_codes
    # Behaviour is unchanged vs the control run with a working recorder.
    assert decision.decision == control_decision.decision
