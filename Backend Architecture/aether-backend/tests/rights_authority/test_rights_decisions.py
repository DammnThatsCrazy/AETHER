"""RightsDecision / RightsLineage / RightsImpact durable record round-trips.

These tests exercise the BaseRepository-backed stores (rights_decisions /
rights_lineage / rights_impacts) and the §4 field contract — including the
fail-closed rule that ``RightsDecision.allowed`` has no implicit default.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from repositories.repos import reset_in_memory_stores

from services.integrations.data_rights.models import (
    RightsDecisionDisposition,
    RightsDerivationClass,
)
from services.rights_authority.contracts import (
    RightsDecision,
    RightsImpact,
    RightsLineage,
)
from services.rights_authority.repositories import (
    rights_decision_repository,
    rights_impact_repository,
    rights_lineage_repository,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _decision(
    *,
    decision_id: str = "rdec_test_1",
    tenant_id: str = "tenant_abc",
    allowed: bool = True,
) -> RightsDecision:
    return RightsDecision(
        decision_id=decision_id,
        tenant_id=tenant_id,
        allowed=allowed,
        disposition=(
            RightsDecisionDisposition.ALLOWED
            if allowed else RightsDecisionDisposition.DENIED
        ),
        reason_codes=[] if allowed else ["no_grant"],
        source_grant_refs=["drg_test_001"],
        ownership_class="contributed_source",
        permitted_uses=["export"],
        evaluated_at="2026-09-07T00:00:00+00:00",
        effective_as_of="2026-09-07T00:00:00+00:00",
    )


async def test_decision_record_get_round_trip():
    decision = _decision()
    await rights_decision_repository.record(decision, identity_key="rdid_abc")
    stored = await rights_decision_repository.get(decision.decision_id)
    assert stored is not None
    assert stored["decision_id"] == decision.decision_id
    assert stored["tenant_id"] == decision.tenant_id
    assert stored["allowed"] is decision.allowed
    assert stored["ownership_class"] == "contributed_source"
    assert stored["identity_key"] == "rdid_abc"


async def test_decision_list_for_tenant_scoping():
    d_t1 = _decision(decision_id="rdec_t1", tenant_id="tenant_1")
    d_t2 = _decision(decision_id="rdec_t2", tenant_id="tenant_2")
    await rights_decision_repository.record(d_t1)
    await rights_decision_repository.record(d_t2)

    tenant_1_rows = await rights_decision_repository.list_for_tenant("tenant_1")
    assert [r["decision_id"] for r in tenant_1_rows] == ["rdec_t1"]
    tenant_2_rows = await rights_decision_repository.list_for_tenant("tenant_2")
    assert [r["decision_id"] for r in tenant_2_rows] == ["rdec_t2"]


async def test_list_known_as_of_filters_by_effective_time():
    early = _decision(decision_id="rdec_early")
    late = _decision(decision_id="rdec_late")
    early = early.model_copy(
        update={"effective_as_of": "2026-09-01T00:00:00+00:00"}
    )
    late = late.model_copy(update={"effective_as_of": "2026-09-08T00:00:00+00:00"})
    await rights_decision_repository.record(early)
    await rights_decision_repository.record(late)

    known = await rights_decision_repository.list_known_as_of(
        "2026-09-05T00:00:00+00:00", tenant_id="tenant_abc"
    )
    ids = {r["decision_id"] for r in known}
    assert "rdec_early" in ids
    assert "rdec_late" not in ids


async def test_decision_find_by_identity():
    decision = _decision(decision_id="rdec_idem")
    await rights_decision_repository.record(decision, identity_key="rdid_same")
    found = await rights_decision_repository.find_by_identity(
        decision.tenant_id, "rdid_same"
    )
    assert found is not None
    assert found["decision_id"] == "rdec_idem"
    missing = await rights_decision_repository.find_by_identity(
        decision.tenant_id, "rdid_other"
    )
    assert missing is None


async def test_allowed_has_no_default():
    """allowed must be explicit — a decision struct cannot silently allow."""
    with pytest.raises(ValidationError):
        RightsDecision(  # type: ignore[call-arg]
            decision_id="rdec_no_allowed",
            tenant_id="tenant_abc",
            disposition=RightsDecisionDisposition.DENIED,
        )


async def test_to_envelope_ref_is_lightweight():
    decision = _decision()
    ref = decision.to_envelope_ref()
    assert set(ref.keys()) == {
        "rights_decision_ref", "rights_policy_version", "evaluated_at",
    }
    assert ref["rights_decision_ref"] == decision.decision_id
    assert ref["rights_policy_version"] == "irrl-2"


async def test_lineage_record_get():
    lineage = RightsLineage(
        artifact_id="art_1",
        parent_artifact_refs=["art_0"],
        source_grant_refs=["drg_test_001"],
        rights_decision_refs=["rdec_test_1"],
        derivation_class=RightsDerivationClass.AETHER_GENERATED_INTELLIGENCE,
        semantic_level="C",
        trust_class="inferred",
        model_refs=["model_1"],
        generated_output_rights_ref="gor_1",
        effective_rights_decision_ref="rdec_test_1",
        tenant_id="tenant_abc",
    )
    await rights_lineage_repository.record(lineage)
    stored = await rights_lineage_repository.get("art_1")
    assert stored is not None
    assert stored["artifact_id"] == "art_1"
    assert stored["derivation_class"] == "aether_generated_intelligence"
    rows = await rights_lineage_repository.list_for_artifact("art_1")
    assert len(rows) == 1


async def test_impact_pending_lifecycle_and_update_state():
    impact = RightsImpact(
        impact_id="rimp_1",
        tenant_id="tenant_abc",
        grant_id="drg_test_001",
        artifact_ref="art_1",
        dependency_kind="vector_embedding",
        responsible_authority="rights_irrl",
        current_state="affected",
    )
    await rights_impact_repository.record(impact)

    pending = await rights_impact_repository.list_pending(tenant_id="tenant_abc")
    assert any(r["impact_id"] == "rimp_1" for r in pending)

    updated = await rights_impact_repository.update_state("rimp_1", "complete")
    assert updated["remediation_state"] == "complete"
    pending_after = await rights_impact_repository.list_pending(tenant_id="tenant_abc")
    assert not any(r["impact_id"] == "rimp_1" for r in pending_after)


async def test_impact_update_state_rejects_unknown_state():
    impact = RightsImpact(
        impact_id="rimp_bad", artifact_ref="art_2", tenant_id="tenant_abc",
    )
    await rights_impact_repository.record(impact)
    with pytest.raises(ValueError):
        await rights_impact_repository.update_state("rimp_bad", "basically_done")
