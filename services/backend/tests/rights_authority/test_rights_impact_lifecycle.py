"""Stream P-B2 — rights impact pipeline + deterministic lifecycle resolution.

Impact pipeline never claims completion without execution (everything stays
``pending`` and is surfaced in ``unresolved``). Lifecycle precedence (§9) picks
the highest decisive level — a legal hold outranks a grant's delete instruction.
"""
import types

import pytest

from repositories.repos import reset_in_memory_stores
from services.rights_authority import impact as impact_mod
from services.rights_authority import lifecycle as lifecycle_mod
from services.rights_authority.generalization import generalized_artifact_repository
from services.integrations.data_rights import service as data_rights_service_module

pytestmark = pytest.mark.asyncio


class _FakeRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

    async def record(self, row: dict) -> dict:
        rid = row.get("decision_id") or row.get("impact_id") or row.get("id")
        assert rid, "record requires an id"
        self._store[rid] = dict(row)
        return dict(row)

    async def get(self, rid: str):
        return self._store.get(rid)

    async def update_state(self, rid: str, data: dict) -> dict:
        if rid in self._store:
            self._store[rid].update(dict(data))
        return dict(self._store.get(rid) or {})

    async def list_for_tenant(self, tenant_id, limit=100, offset=0, extra=None):
        rows = [r for r in self._store.values() if r.get("tenant_id") == tenant_id]
        if extra:
            rows = [r for r in rows if all(r.get(k) == v for k, v in extra.items())]
        return rows[offset:offset + limit]

    async def list_pending(self, tenant_id=None, limit=200):
        rows = [r for r in self._store.values() if r.get("remediation_state") == "pending"]
        if tenant_id:
            rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        return rows[:limit]


_TEST_GRANTS = {
    "g_1": types.SimpleNamespace(
        data_rights_grant_id="g_1",
        tenant_id="t1",
        status="active",
        source_id="source_1",
    ),
}


async def _load_grant_for_test(grant_id: str):
    return _TEST_GRANTS.get(grant_id)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_in_memory_stores()
    repos = types.SimpleNamespace(
        rights_decision_repository=_FakeRepo(),
        rights_lineage_repository=_FakeRepo(),
        rights_impact_repository=_FakeRepo(),
    )
    monkeypatch.setattr(impact_mod, "_pb1_repositories", lambda: repos)
    monkeypatch.setattr(lifecycle_mod, "_pb1_repositories", lambda: repos)
    monkeypatch.setattr(impact_mod, "_grant_loader", _load_grant_for_test)
    async def _revoke(grant_id, body):
        grant = _TEST_GRANTS.get(grant_id)
        if grant is None:
            return None
        values = vars(grant).copy()
        values.update(status="revoked", revoked_at="2026-09-09T00:00:00Z")
        updated = types.SimpleNamespace(**values)
        _TEST_GRANTS[grant_id] = updated
        return updated
    monkeypatch.setattr(data_rights_service_module.data_rights_service, "revoke_grant", _revoke)
    yield repos
    reset_in_memory_stores()


# ═══════════════════════════════════════════════════════════════════════════
# Impact pipeline
# ═══════════════════════════════════════════════════════════════════════════

async def test_compute_rights_impact_covers_all_cascade_dimensions_pending():
    items = impact_mod.compute_rights_impact("t1", grant_id="g_1")
    assert {i.component_type for i in items} == set(
        impact_mod.RIGHTS_IMPACT_DIMENSIONS
    )
    for item in items:
        assert item.remediation_state == "pending"
        assert item.tenant_id == "t1"
    by_dim = {i.component_type: i for i in items}
    assert by_dim["raw_object"].required_action == "hard_delete"
    assert by_dim["vector_embedding"].required_action == "recompute_or_delete"
    # Export defaults delete (delivery evidence would flip to tenant_retains).
    assert by_dim["exported_artifact"].required_action == "delete"


async def test_revocation_pipeline_no_fake_completion():
    # Seed one generalized artifact that derived from the revoked grant.
    await generalized_artifact_repository.record({
        "generalized_artifact_id": "gart_seed",
        "tenant_id": "t1",
        "parent_artifact_refs": ["obs_1"],
        "transformation_refs": [],
        "generalization_policy_version": "irrl-2",
        "rights_decision_ref": "rdec_seed",
        "source_grant_refs": ["g_1"],
        "tenant_identifiable": False,
        "reidentification_risk": "low",
        "minimum_population_met": True,
        "lineage_ref": "obs_1",
        "permitted_destinations": ["olympus_graph"],
        "retention_policy_ref": None,
        "evidence_refs": [],
        "created_at": "2026-09-07T00:00:00Z",
    })

    summary = await impact_mod.revocation_pipeline(
        tenant_id="t1", grant_id="g_1", reason="tenant revoked consent"
    )

    # Immediate future-use denial recorded.
    assert len(summary.revocation_decision_refs) == 1
    assert len(summary.impact_ids) == len(impact_mod.RIGHTS_IMPACT_DIMENSIONS) + 1

    # The generalized derivative was marked for re-generalization recheck.
    assert len(summary.generalized_recheck_ids) == 1

    # Everything is still pending — nothing was faked complete.
    stored = await impact_mod.list_pending_impacts("t1")
    assert len(stored) >= len(impact_mod.RIGHTS_IMPACT_DIMENSIONS)
    assert all(r["remediation_state"] == "pending" for r in stored)
    # Every pending impact is surfaced as unresolved.
    assert set(summary.unresolved) <= set(summary.impact_ids)
    assert summary.unresolved


async def test_revocation_refuses_unknown_grant_and_records_nothing():
    with pytest.raises(impact_mod.RevocationError):
        await impact_mod.revocation_pipeline(
            tenant_id="t1", grant_id="g_missing", reason="operator request"
        )
    stored = await impact_mod.list_pending_impacts("t1")
    assert stored == []


async def test_revocation_refuses_cross_tenant_grant_and_records_nothing():
    # g_1 is owned by t1 — a t2 caller must be refused with nothing recorded.
    with pytest.raises(impact_mod.RevocationError):
        await impact_mod.revocation_pipeline(
            tenant_id="t2", grant_id="g_1", reason="operator request"
        )
    stored = await impact_mod.list_pending_impacts("t2")
    assert stored == []


# ═══════════════════════════════════════════════════════════════════════════
# Lifecycle precedence (§9)
# ═══════════════════════════════════════════════════════════════════════════

async def test_lifecycle_precedence_legal_hold_over_grant_delete():
    grant = types.SimpleNamespace(lifecycle_action="delete", tenant_id="t1")
    resolution = await lifecycle_mod.resolve_effective_lifecycle(
        tenant_id="t1",
        artifact_ref="artifact_1",
        grant=grant,
        legal_hold={"active": True, "legal_hold_id": "hold_1"},
    )
    assert resolution.action == "legal_hold"
    assert resolution.basis == "level_2_legal_hold"
    assert resolution.decision_ref is not None and resolution.decision_ref.startswith("rdec_")


async def test_lifecycle_legal_prohibition_beats_hold():
    resolution = await lifecycle_mod.resolve_effective_lifecycle(
        tenant_id="t1",
        grant=types.SimpleNamespace(lifecycle_action="delete"),
        legal_hold={"active": True},
        legal_prohibition={"action": "delete"},
    )
    assert resolution.action == "delete"
    assert resolution.basis == "level_1_legal_prohibition"


async def test_lifecycle_event_retention_class_level_7():
    resolution = await lifecycle_mod.resolve_effective_lifecycle(
        tenant_id="t1",
        event_retention_class="event_class_analytics",
    )
    assert resolution.action == "delete"
    assert resolution.basis == "level_7_event_retention_class"


async def test_deletion_cascade_is_dependency_aware():
    resolution = lifecycle_mod.LifecycleResolution(
        tenant_id="t1",
        action="delete",
        basis="level_1_legal_prohibition",
        basis_label="Legal prohibition / mandatory deletion",
    )
    cascade = resolution.deletion_cascade({
        "raw:obs_1": "raw_object",
        "embedding:obs_1": "vector_embedding",
        "export:file_1": "exported_artifact",
        "model:w_1": "model_weight",
    })
    by_ref = {r["component_ref"]: r for r in cascade}
    assert by_ref["raw:obs_1"]["action"] == "hard_delete"
    assert by_ref["embedding:obs_1"]["action"] == "recompute_or_delete"
    assert by_ref["export:file_1"]["action"] == "tenant_retains"
    assert by_ref["model:w_1"]["action"] == "retrain_or_evaluation"
    assert len(cascade) == 4


async def test_deletion_cascade_preserve_propagates_non_destructive_action():
    resolution = lifecycle_mod.LifecycleResolution(
        tenant_id="t1",
        action="legal_hold",
        basis="level_2_legal_hold",
        basis_label="Legal hold / preservation obligation",
    )
    cascade = resolution.deletion_cascade({
        "raw:obs_1": "raw_object",
        "embedding:obs_1": "vector_embedding",
    })
    assert all(r["action"] == "legal_hold" for r in cascade)
