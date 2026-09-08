"""Effective Rights Resolver — fail-closed matrix + structured positive paths.

Fail-closed is the prime directive: missing/unknown rights deny; a legacy grant
that never granted training stays denied; an explicit structured learning
authority is honored (migration map `model_training_allowed` →
`contributed_model_training` is applied by the P-A helpers the resolver calls).

P-A (services.integrations.data_rights.models) owns the structured contracts and
migration helpers; the orchestrator lands P-A before these tests run.
"""
from __future__ import annotations

from typing import Optional

import pytest

from repositories.repos import reset_in_memory_stores

from services.integrations.data_rights.models import (
    DataRightsGrant,
    GrantStatus,
    LearningAuthority,
    RightsDecisionDisposition,
)
from services.integrations.data_rights.service import (
    default_disclosure_authority,
    default_generated_output_rights,
)
from services.rights_authority.resolver import EffectiveRightsResolver

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _grant(**overrides) -> DataRightsGrant:
    base = {
        "data_rights_grant_id": "drg_test_001",
        "tenant_id": "tenant_abc",
        "contract_id": None,
        "source_id": "src_001",
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


def _loader(*grants: DataRightsGrant):
    async def _load(tenant_id: str, source_id: str) -> Optional[DataRightsGrant]:
        for grant in grants:
            if grant.tenant_id == tenant_id and grant.source_id == source_id:
                return grant
        return None
    return _load


async def test_no_grant_denied_fail_closed():
    resolver = EffectiveRightsResolver(grant_loader=_loader())
    decision = await resolver.resolve(
        "tenant_abc", "src_missing", None, "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is False
    assert decision.disposition == RightsDecisionDisposition.DENIED
    assert "no_grant" in decision.reason_codes
    assert decision.source_grant_refs == []


async def test_revoked_grant_denied():
    grant = _grant(status=GrantStatus.REVOKED, revoked_at="2026-09-05T00:00:00+00:00")
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "tenant_graph", "operations", "tenant",
    )
    assert decision.allowed is False
    assert decision.disposition == RightsDecisionDisposition.DENIED
    assert "grant_revoked" in decision.reason_codes


async def test_expired_grant_denied():
    grant = _grant(expires_at="2026-09-02T00:00:00+00:00")
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "tenant_graph", "operations", "tenant",
    )
    assert decision.allowed is False
    assert "grant_expired" in decision.reason_codes


async def test_unknown_use_denied():
    grant = _grant()
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "frobnicate", "operations", "tenant",
    )
    assert decision.allowed is False
    assert decision.disposition == RightsDecisionDisposition.DENIED
    assert "unknown_use" in decision.reason_codes


async def test_legacy_training_denied_while_baseline_allowed():
    """model_training_allowed=False denies train; olympus baseline stays usable."""
    grant = _grant(olympus_baseline_allowed=True, model_training_allowed=False)
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))

    train = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "train", "model_training", "olympus",
    )
    assert train.allowed is False
    assert "contributed_model_training" in train.reason_codes

    baseline = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "olympus_baseline", "operations", "olympus",
    )
    assert baseline.allowed is True
    assert baseline.disposition == RightsDecisionDisposition.ALLOWED
    assert "olympus_baseline" in baseline.permitted_uses


async def test_training_denied_when_structured_learning_explicitly_false():
    """Structured learning authority false wins even when legacy baseline is true."""
    learning = LearningAuthority(contributed_model_training=False)
    grant = _grant(
        olympus_baseline_allowed=True,
        model_training_allowed=False,
        learning_authority=learning,
    )
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    train = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "train", "model_training", "olympus",
    )
    assert train.allowed is False
    assert "contributed_model_training" in train.reason_codes


async def test_learning_authority_true_only_when_set_explicitly():
    """Explicit structured contributed_model_training=True overrides legacy False."""
    learning = LearningAuthority(contributed_model_training=True)
    grant = _grant(model_training_allowed=False, learning_authority=learning)
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "train", "model_training", "olympus",
    )
    assert decision.allowed is True
    assert decision.disposition == RightsDecisionDisposition.ALLOWED
    assert decision.reason_codes == []
    assert "contributed_model_training" in decision.permitted_learning


async def test_structured_export_allowed_with_generated_output_defaults():
    """STANDARD-profile grant with default generated-output rights → export."""
    grant = _grant(
        connector_class="tenant_byod_data",
        generated_output_rights=default_generated_output_rights(),
        rights_profile="standard",
    )
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_gen_1", "actor_1",
        "export", "tenant_analytics", "tenant",
    )
    assert decision.allowed is True
    assert decision.disposition == RightsDecisionDisposition.ALLOWED
    assert decision.reason_codes == []
    assert grant.data_rights_grant_id in decision.source_grant_refs
    assert "export" in decision.permitted_uses
    assert "tenant_export" in decision.permitted_uses


async def test_export_denied_without_generated_output_rights():
    """No structured generated-output rights → export fails closed."""
    grant = _grant(connector_class="tenant_byod_data")
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "export", "tenant_analytics", "tenant",
    )
    assert decision.allowed is False
    assert "export" in decision.reason_codes


async def test_olympus_internal_purpose_allowlist_allows_known_purpose():
    grant = _grant(
        olympus_baseline_allowed=True,
        generated_output_rights=default_generated_output_rights(),
        disclosure_authority=default_disclosure_authority(),
    )
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "OLYMPUS_INTERNAL",
        "olympus_internal", "platform_research", "olympus",
    )
    assert decision.allowed is True
    assert decision.disposition == RightsDecisionDisposition.ALLOWED
    assert "olympus_internal" in decision.permitted_disclosures


async def test_olympus_internal_unknown_purpose_denied():
    grant = _grant(
        olympus_baseline_allowed=True,
        generated_output_rights=default_generated_output_rights(),
        disclosure_authority=default_disclosure_authority(),
    )
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "OLYMPUS_INTERNAL",
        "olympus_internal", "share_with_competitor", "olympus",
    )
    assert decision.allowed is False
    assert decision.disposition == RightsDecisionDisposition.DENIED
    assert "olympus_purpose_not_allowed" in decision.reason_codes


async def test_historic_as_of_outside_grant_window_denied():
    grant = _grant(
        granted_at="2026-09-10T00:00:00+00:00",
        expires_at="2026-09-20T00:00:00+00:00",
    )
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    before_grant = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "tenant_insights", "operations", "tenant",
        as_of="2026-09-01T00:00:00+00:00",
    )
    assert before_grant.allowed is False
    assert "not_effective_as_of" in before_grant.reason_codes

    after_expiry = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "tenant_insights", "operations", "tenant",
        as_of="2026-09-25T00:00:00+00:00",
    )
    assert after_expiry.allowed is False
    assert "grant_expired" in after_expiry.reason_codes


async def test_decision_idempotency_returns_same_decision_id():
    """Blueprint §17: identical inputs never yield conflicting decisions."""
    learning = LearningAuthority(contributed_model_training=True)
    grant = _grant(model_training_allowed=False, learning_authority=learning)
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))

    first = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_1", "actor_1",
        "train", "model_training", "olympus",
    )
    second = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_1", "actor_1",
        "train", "model_training", "olympus",
    )
    assert first.allowed is True
    assert second.allowed is True
    assert first.decision_id == second.decision_id
