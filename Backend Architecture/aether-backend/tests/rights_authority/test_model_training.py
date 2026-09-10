"""Rights Authority training-manifest VERIFICATION adapter tests.

A candidate training request must clear both model-governance gates
(validate_training_manifest + model_training_eligibility). A block is made
durable + surfaced as a pending ``model_training_input`` impact item; an
eligible request fabricates nothing.
"""
from __future__ import annotations

import types

import pytest

from repositories.repos import reset_in_memory_stores
from services.rights_authority import impact as impact_mod
from services.rights_authority import model_training as model_training_mod
from services.rights_authority.model_governance import (
    TrainingDataManifest,
    validate_training_manifest,
)
from services.rights_authority.model_training import (
    TRAINING_BLOCK_ACTION,
    TRAINING_BLOCK_COMPONENT_TYPE,
    evaluate_training_manifest,
    verify_training_request,
)

pytestmark = pytest.mark.asyncio


class _FakeDecisionRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def seed(self, row: dict) -> None:
        rid = row.get("decision_id") or row.get("id")
        assert rid, "seed requires a decision_id"
        self._store[rid] = dict(row)

    async def record(self, row: dict) -> dict:
        rid = row.get("decision_id") or row.get("id")
        assert rid, "record requires a decision_id"
        self._store[rid] = dict(row)
        return dict(row)

    async def get(self, rid: str):
        return self._store.get(rid)


class _FakeImpactRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    async def record(self, row: dict) -> dict:
        rid = row.get("impact_id") or row.get("decision_id") or row.get("id")
        assert rid, "record requires an id"
        self._store[rid] = dict(row)
        return dict(row)

    async def get(self, rid: str):
        return self._store.get(rid)

    async def list_for_tenant(self, tenant_id, limit=200, offset=0, extra=None):
        rows = [r for r in self._store.values() if r.get("tenant_id") == tenant_id]
        if extra:
            rows = [r for r in rows if all(r.get(k) == v for k, v in extra.items())]
        return rows[offset:offset + limit]

    async def list_pending(self, tenant_id=None, limit=200):
        rows = [r for r in self._store.values() if r.get("remediation_state") == "pending"]
        if tenant_id:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        return rows[:limit]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_in_memory_stores()
    impact_repo = _FakeImpactRepo()
    repos = types.SimpleNamespace(
        rights_decision_repository=_FakeDecisionRepo(),
        rights_lineage_repository=_FakeImpactRepo(),
        rights_impact_repository=impact_repo,
    )
    monkeypatch.setattr(impact_mod, "_pb1_repositories", lambda: repos)
    yield repos
    reset_in_memory_stores()


def _training_grant(*, allows_training: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        data_rights_grant_id="drg_1",
        tenant_id="t1",
        source_id="src1",
        status="active",
        model_training_allowed=allows_training,
    )


def _eligible_manifest() -> TrainingDataManifest:
    return TrainingDataManifest(
        run_id="run_ok",
        tenant_id="t1",
        model_ref="model_ok",
        dataset_artifact_refs=["dataset_a"],
        rights_decision_refs=["rdec_train_a"],
        learning_authority_classes=["contributed_model_training"],
        exclusion_count=0,
    )


def _seed_training_decision(decision_repo: _FakeDecisionRepo) -> None:
    decision_repo.seed({
        "decision_id": "rdec_train_a",
        "tenant_id": "t1",
        "allowed": True,
        "requested_use": "model_training",
        "artifact_ref": "dataset_a",
        "policy_version": "irrl-2",
    })


# ═══════════════════════════════════════════════════════════════════════════
# Eligible manifest → passes, no fabricated impact
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_verify_eligible_manifest_passes_with_no_impact():
    decision_repo = _FakeDecisionRepo()
    _seed_training_decision(decision_repo)
    verification = await verify_training_request(
        manifest=_eligible_manifest(),
        tenant_id="t1",
        source_id="src1",
        grants=[_training_grant(allows_training=True)],
        decision_repository=decision_repo,
    )
    assert verification.eligible is True
    assert verification.blocked is False
    assert verification.manifest_eligible is True
    assert verification.eligibility_eligible is True
    assert verification.denial_reason_codes == []
    assert verification.pending_impact is None
    assert verification.impact_ids == []
    assert verification.persisted is False
    assert await impact_mod.list_pending_impacts("t1") == []


@pytest.mark.asyncio
async def test_manifest_decisions_are_bound_to_training_tenant():
    decision_repo = _FakeDecisionRepo()
    decision_repo.seed({
        "decision_id": "foreign-decision",
        "tenant_id": "tenant-b",
        "allowed": True,
        "requested_use": "model_training",
        "artifact_ref": "dataset_a",
    })
    manifest = TrainingDataManifest(
        run_id="run-cross-tenant",
        tenant_id="tenant-a",
        model_ref="model-cross-tenant",
        dataset_artifact_refs=["dataset_a"],
        rights_decision_refs=["foreign-decision"],
        exclusion_count=0,
    )

    report = await validate_training_manifest(manifest, decision_repository=decision_repo)

    assert report.eligible is False
    assert "decision_tenant_mismatch" in report.denial_reason_codes
    assert "missing_rights_evidence" in report.denial_reason_codes


# ═══════════════════════════════════════════════════════════════════════════
# Blocked manifest → durable pending model_training_input impact item
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_verify_blocked_manifest_records_durable_pending_impact():
    # No matching training decision + a grant that never authorised training.
    decision_repo = _FakeDecisionRepo()
    manifest = TrainingDataManifest(
        run_id="run_blocked",
        model_ref="model_blocked",
        dataset_artifact_refs=["dataset_z"],
        rights_decision_refs=["rdec_missing"],
        learning_authority_classes=["contributed_model_training"],
        exclusion_count=0,
    )
    verification = await verify_training_request(
        manifest=manifest,
        tenant_id="t1",
        source_id="src1",
        grants=[_training_grant(allows_training=False)],
        decision_repository=decision_repo,
    )
    assert verification.eligible is False
    assert verification.blocked is True
    assert "missing_rights_evidence" in verification.denial_reason_codes
    assert verification.manifest_eligible is False
    assert verification.eligibility_eligible is False

    # Durable + surfaced block, pending, on the model_training_input dimension.
    assert verification.pending_impact is not None
    pending_impact = verification.pending_impact
    assert pending_impact.component_type == TRAINING_BLOCK_COMPONENT_TYPE
    assert pending_impact.required_action == TRAINING_BLOCK_ACTION
    assert pending_impact.remediation_state == "pending"
    assert pending_impact.tenant_id == "t1"
    assert "no training input consumed" in pending_impact.reason
    assert len(verification.impact_ids) == 1
    assert verification.persisted is True

    stored = await impact_mod.list_pending_impacts("t1")
    assert len(stored) == 1
    assert stored[0]["remediation_state"] == "pending"
    assert stored[0]["component_type"] == "model_training_input"


@pytest.mark.asyncio
async def test_evaluate_returns_block_item_without_persisting_when_disabled():
    decision_repo = _FakeDecisionRepo()
    manifest = TrainingDataManifest(
        run_id="run_blocked2",
        model_ref="model_blocked2",
        dataset_artifact_refs=["dataset_z"],
        rights_decision_refs=["rdec_missing"],
        learning_authority_classes=["contributed_model_training"],
        exclusion_count=0,
    )
    verification = await verify_training_request(
        manifest=manifest,
        tenant_id="t1",
        source_id="src1",
        grants=[_training_grant(allows_training=False)],
        decision_repository=decision_repo,
        persist_block=False,
    )
    assert verification.blocked is True
    assert verification.pending_impact is not None
    assert verification.impact_ids == []
    assert verification.persisted is False
    assert await impact_mod.list_pending_impacts("t1") == []


@pytest.mark.asyncio
async def test_evaluate_training_manifest_matches_model_governance_signature():
    # Same ineligible manifest; the adapter must reuse model_governance semantics.
    decision_repo = _FakeDecisionRepo()
    manifest = _eligible_manifest()
    verification = await evaluate_training_manifest(
        manifest=manifest,
        tenant_id="t1",
        source_id="src1",
        grants=[_training_grant(allows_training=False)],
        decision_repository=decision_repo,
    )
    # Without the backing decision + training authorisation the manifest is denied
    # exactly as model_governance.validate_training_manifest would deny it.
    assert verification.eligible is False
    assert "missing_rights_evidence" in verification.denial_reason_codes
    assert verification.manifest_report["eligible"] is False
    assert verification.eligibility_report["eligible"] is False
