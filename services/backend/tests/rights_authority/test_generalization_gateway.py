"""Stream P-B2 — Generalization Gateway tests.

Fail-closed negative + golden positive path. The P-A / P-B1 modules (structured
grant contracts, RightsDecision repositories/resolver) are developed in parallel
streams and may not have landed when this suite runs, so the gateway's
*canonical collaborator accessors* (module-level ``_pb1_repositories`` /
``_pb1_resolver``) are patched with faithful in-memory stand-ins that mirror the
frozen blueprint surface. When the real modules land the same accessor functions
point at them and this suite exercises the true integration.
"""
import types

import pytest
from types import SimpleNamespace

from repositories.repos import reset_in_memory_stores
from services.rights_authority import generalization as gateway_mod

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════════════
# In-memory stand-ins mirroring the P-B1 repository surface
# (record/get/list_for_tenant/list_pending/update_state).
# ═══════════════════════════════════════════════════════════════════════════

class _FakeRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

    async def record(self, row: dict) -> dict:
        rid = row.get("decision_id") or row.get("id")
        assert rid, "record requires a decision_id/id"
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


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_in_memory_stores()
    repos = types.SimpleNamespace(
        rights_decision_repository=_FakeRepo(),
        rights_lineage_repository=_FakeRepo(),
        rights_impact_repository=_FakeRepo(),
    )
    monkeypatch.setattr(gateway_mod, "_pb1_repositories", lambda: repos)
    def _resolver_unavailable():
        raise ImportError("resolver not yet available")

    monkeypatch.setattr(gateway_mod, "_pb1_resolver", _resolver_unavailable)
    yield repos
    reset_in_memory_stores()


def _structured_grant(
    *,
    grant_id="g_1",
    tenant_id="tenant_a",
    source_id="source_x",
    generalized_learning=True,
    contributed_model_training=True,
    generalized_cross_tenant=True,
    olympus_baseline=True,
    status="active",
):
    return SimpleNamespace(
        data_rights_grant_id=grant_id,
        tenant_id=tenant_id,
        source_id=source_id,
        status=status,
        revoked_at=None,
        expires_at=None,
        learning_authority=SimpleNamespace(
            generalized_learning=generalized_learning,
            contributed_model_training=contributed_model_training,
            inference=True,
            tenant_adaptation=True,
        ),
        disclosure_authority=SimpleNamespace(
            generalized_cross_tenant=generalized_cross_tenant,
            cross_tenant_identifiable=False,
            generalized_external=True,
        ),
        source_use=SimpleNamespace(olympus_baseline=olympus_baseline),
    )


def _request(destination="olympus_graph", evidence=True):
    return gateway_mod.GeneralizationRequest(
        artifact_ref="artifact_contrib_1",
        tenant_id="tenant_a",
        requested_destination=destination,
        requested_use="generalize",
        evidence_refs=["evidence.artifact_profile_1"] if evidence else [],
        rights_refs=["g_1"],
        actor="platform",
        purpose="platform_knowledge",
    )


def _safe_context(grants):
    return gateway_mod.GeneralizationEligibilityContext(
        grants=grants,
        consent_allowed=True,
        pii_present=False,
        tenant_identifiable=False,
        reidentification_risk="low",
        minimum_population=5000,
        lineage_complete=True,
        derivation_class="aggregated",
        data_sensitivity="unclassified",
    )


async def test_golden_path_allows_transformed_artifact_into_destination():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph")
    ctx = _safe_context([_structured_grant()])
    decision = await gateway.evaluate(request, context=ctx)
    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert decision.requested_destination == "olympus_graph"
    assert "generalized_learning" or decision.permitted_uses

    artifact = await gateway.apply(request, decision, context=ctx)
    assert artifact.tenant_identifiable is False
    assert artifact.minimum_population_met is True
    assert artifact.reidentification_risk in ("low", "medium")
    assert artifact.permitted_destinations == ["olympus_graph"]
    # apply() re-evaluates authoritatively — it never trusts the caller-supplied
    # decision object — and binds the artifact to the fresh durable decision.
    fresh = await gateway_mod._pb1_repositories().rights_decision_repository.get(
        artifact.rights_decision_ref
    )
    assert fresh is not None and fresh.get("allowed") is True
    assert artifact.generalization_policy_version == "irrl-2"

    # The artifact is recorded in the generalized-artifact store.
    row = await gateway_mod.generalized_artifact_repository.get(
        artifact.generalized_artifact_id
    )
    assert row is not None
    assert row["permitted_destinations"] == ["olympus_graph"]


async def test_denies_when_tenant_identifiable_and_unremovable():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph")
    ctx = _safe_context([_structured_grant()])
    # tenant-identifiable with high residual risk cannot be reliably removed.
    ctx.tenant_identifiable = True
    ctx.reidentification_risk = "high"
    decision = await gateway.evaluate(request, context=ctx)
    assert decision.allowed is False
    assert "tenant_identifiable_not_removable" in decision.denial_reason_codes
    assert "reidentification_risk_high" in decision.denial_reason_codes


async def test_denies_when_evidence_missing_or_unverifiable():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph", evidence=False)
    # No evidence refs and every context signal left unknown → conservative deny.
    decision = await gateway.evaluate(
        request,
        context=gateway_mod.GeneralizationEligibilityContext(
            grants=[_structured_grant()]
        ),
    )
    assert decision.allowed is False
    assert "missing_evidence" in decision.denial_reason_codes
    assert "pii_unverifiable" in decision.denial_reason_codes
    assert "tenant_identifiability_unverifiable" in decision.denial_reason_codes
    assert "lineage_incomplete" in decision.denial_reason_codes


async def test_model_training_destination_requires_explicit_contribution():
    gateway = gateway_mod.generalization_gateway
    grant = _structured_grant(contributed_model_training=False)
    request = _request(destination="model_training")
    ctx = _safe_context([grant])
    decision = await gateway.evaluate(request, context=ctx)
    assert decision.allowed is False
    assert "learning_authority_denied" in decision.denial_reason_codes


async def test_only_gateway_path_flags_olympus_knowledge():
    gateway = gateway_mod.generalization_gateway
    # A hand-made "generalized-looking" artifact NOT produced through the gateway
    # must never be eligible for Olympus knowledge.
    forged = gateway_mod.GeneralizedArtifact(
        tenant_id="tenant_a",
        parent_artifact_refs=["artifact_contrib_1"],
        tenant_identifiable=False,
        reidentification_risk="low",
        minimum_population_met=True,
        lineage_ref="artifact_contrib_1",
        permitted_destinations=["olympus_graph"],
        rights_decision_ref=None,  # no durable decision → not through the gateway
    )
    assert await gateway.is_eligible_for_olympus_knowledge(forged) is False

    # And a fully-transformed, gateway-produced artifact IS the only path.
    request = _request(destination="olympus_graph")
    ctx = _safe_context([_structured_grant()])
    decision = await gateway.evaluate(request, context=ctx)
    artifact = await gateway.apply(request, decision, context=ctx)
    assert await gateway.is_eligible_for_olympus_knowledge(artifact) is True


async def test_apply_refuses_disallowed_decision():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph")
    ctx = _safe_context([_structured_grant()])
    ctx.tenant_identifiable = True
    ctx.reidentification_risk = "high"
    decision = await gateway.evaluate(request, context=ctx)
    assert decision.allowed is False
    with pytest.raises(gateway_mod.GeneralizationDeniedError):
        await gateway.apply(request, decision, context=ctx)


async def test_apply_never_trusts_a_fabricated_allowed_decision():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph")
    # A forged allowed decision (never persisted, never evaluated) must NOT
    # materialise an artifact: apply() re-evaluates and uses only that result.
    forged = gateway_mod.GeneralizationDecision(
        tenant_id=request.tenant_id,
        artifact_ref=request.artifact_ref,
        requested_destination="olympus_graph",
        requested_use="generalize",
        allowed=True,
        disposition="allow",
    )
    with pytest.raises(gateway_mod.GeneralizationDeniedError):
        # Empty context → the authoritative re-evaluation fails closed.
        await gateway.apply(request, forged)


async def test_apply_requires_executed_payload_before_stamping_deidentified():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph")
    ctx = _safe_context([_structured_grant()])
    # Tenant-identifiable but removable (low residual risk): evaluation ALLOWS
    # only with the three de-identification transformations required.
    ctx.tenant_identifiable = True
    ctx.reidentification_risk = "low"
    decision = await gateway.evaluate(request, context=ctx)
    assert decision.allowed is True
    assert "tenant_identifier_removal" in decision.required_transformations

    # No payload → must NOT stamp a de-identified artifact (execution, not intent).
    with pytest.raises(gateway_mod.GeneralizationDeniedError):
        await gateway.apply(request, decision, context=ctx)
    # Payload without the required per-kind key lists → still refused.
    with pytest.raises(gateway_mod.GeneralizationDeniedError):
        await gateway.apply(
            request, decision, context=ctx, payload={"email": "a@b.co"}
        )


async def test_apply_executes_required_transformations_before_stamping():
    gateway = gateway_mod.generalization_gateway
    request = _request(destination="olympus_graph")
    ctx = _safe_context([_structured_grant()])
    ctx.tenant_identifiable = True
    ctx.reidentification_risk = "low"
    decision = await gateway.evaluate(request, context=ctx)
    assert decision.allowed is True
    assert len(decision.required_transformations) == 3

    artifact = await gateway.apply(
        request,
        decision,
        context=ctx,
        payload={
            "tenant_uuid": "t-1",
            "email": "a@b.co",
            "namespace": "tenant_a.config",
            "score": 0.9,
        },
        deidentification_keys={
            "tenant_identifier_removal": ["tenant_uuid"],
            "pii_strip": ["email"],
            "tenant_metadata_strip": ["namespace"],
        },
    )
    assert artifact.tenant_identifiable is False
    # All three required de-identification kinds were executed and are evidenced
    # on the artifact's transformation records.
    assert len(artifact.transformation_refs) == 3


async def test_transformation_apply_helpers_are_pure_and_evidence_linked():
    # pii_strip removes PII-tagged keys.
    stripped, note = gateway_mod.TRANSFORMATION_APPLY["pii_strip"](
        {"email": "a@b.co", "score": 1.0}, pii_keys=["email"]
    )
    assert "email" not in stripped
    assert "score" in stripped
    assert "PII" in note

    # tenant_identifier_removal removes tenant keys.
    purged, _ = gateway_mod.TRANSFORMATION_APPLY["tenant_identifier_removal"](
        {"tenant_uuid": "t-1", "event": "x"}, tenant_id_keys=["tenant_uuid"]
    )
    assert "tenant_uuid" not in purged

    # distribution_aggregation suppresses a cohort below the minimum population
    # instead of fabricating an aggregate (never unknown → 0).
    summary, note = gateway_mod.TRANSFORMATION_APPLY["distribution_aggregation"](
        [{"v": 1.0}, {"v": 2.0}], "v", min_population=25
    )
    assert summary is None
    assert "suppressed" in note
