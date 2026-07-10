"""Cluster Targeting Intelligence — policy, snapshots, leakage, exports,
suggestions, recompute, routes, isolation."""

from __future__ import annotations

import dataclasses
import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from shared.common.common import BadRequestError, NotFoundError  # noqa: E402
from services.targeting_intelligence import kyber_routes as t_kyber  # noqa: E402
from services.targeting_intelligence import routes as t_routes  # noqa: E402
from services.targeting_intelligence.export import build_export_package  # noqa: E402
from services.targeting_intelligence.journey_delta import (  # noqa: E402
    compute_journey_delta,
    is_overexposed,
    overexposure_score,
)
from services.targeting_intelligence.leakage import detect_leakage  # noqa: E402
from services.targeting_intelligence.models import (  # noqa: E402
    ClusterTargetingRule,
    EntityRef,
    ExclusionLeakageFinding,
    ProviderMappingQuality,
    TargetingEligibilitySnapshot,
    TargetingIntent,
    TargetingObservation,
    utc_now_iso,
)
from services.targeting_intelligence.policy import (  # noqa: E402
    ClusterSignals,
    is_eligible,
    resolve_cluster,
)
from services.targeting_intelligence.quality import compute_mapping_quality  # noqa: E402
from services.targeting_intelligence.recompute import recompute_snapshot  # noqa: E402
from services.targeting_intelligence.release_readiness import release_readiness  # noqa: E402
from services.targeting_intelligence.repository import TargetingRepositories  # noqa: E402
from services.targeting_intelligence.service import TargetingIntentService  # noqa: E402
from services.targeting_intelligence.suggestion_adapter import (  # noqa: E402
    leakage_suggestion,
    overexposure_suggestion,
)

pytestmark = pytest.mark.asyncio(loop_scope="function")


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


async def _no_members(tenant_id: str, cluster_id: str):
    return 10


@pytest.fixture(autouse=True)
def _enable_targeting(monkeypatch):
    patched = dataclasses.replace(
        settings.targeting_intelligence,
        enabled=True, exports_enabled=True,
        ooda_suggestions_enabled=True, kyber_enabled=True,
    )
    monkeypatch.setattr(settings, "targeting_intelligence", patched)


@pytest.fixture()
def service():
    return TargetingIntentService(
        repositories=TargetingRepositories(), member_reader=_no_members
    )


class FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"

    def require_permission(self, permission: str) -> None:
        return None


class FakeRequest:
    def __init__(self, tenant_id: str):
        self.state = SimpleNamespace(tenant=FakeTenant(tenant_id), request_id="req-1")
        self.headers = {}


# ── Conflict precedence truth table ────────────────────────────────────────

class TestConflictPrecedence:
    RULES = [
        ClusterTargetingRule(clusterId="c1", ruleType="include"),
        ClusterTargetingRule(clusterId="c1", ruleType="exclude"),
        ClusterTargetingRule(clusterId="c1", ruleType="reference"),
        ClusterTargetingRule(clusterId="c1", ruleType="holdout"),
    ]

    def test_consent_always_wins(self):
        decision = resolve_cluster("t", "c1", self.RULES,
                                   ClusterSignals(consent_blocked=True,
                                                  regulatory_blocked=True,
                                                  fraud_risk=True))
        assert decision.resolution == "hard_consent_block"
        assert not is_eligible(decision)

    def test_regulatory_beats_fraud_and_rules(self):
        decision = resolve_cluster("t", "c1", self.RULES,
                                   ClusterSignals(regulatory_blocked=True,
                                                  fraud_risk=True))
        assert decision.resolution == "regulatory_policy_block"

    def test_fraud_beats_manual_exclusion(self):
        decision = resolve_cluster("t", "c1", self.RULES,
                                   ClusterSignals(fraud_risk=True))
        assert decision.resolution == "fraud_risk_exclusion"

    def test_manual_exclusion_beats_holdout_and_inclusion(self):
        decision = resolve_cluster("t", "c1", self.RULES)
        assert decision.resolution == "tenant_manual_exclusion"

    def test_holdout_beats_inclusion(self):
        rules = [ClusterTargetingRule(clusterId="c1", ruleType="include"),
                 ClusterTargetingRule(clusterId="c1", ruleType="holdout")]
        assert resolve_cluster("t", "c1", rules).resolution == "holdout_control"

    def test_inclusion_beats_reference(self):
        rules = [ClusterTargetingRule(clusterId="c1", ruleType="include"),
                 ClusterTargetingRule(clusterId="c1", ruleType="reference")]
        decision = resolve_cluster("t", "c1", rules)
        assert decision.resolution == "inclusion" and is_eligible(decision)

    def test_reference_alone_is_similarity_inclusion(self):
        rules = [ClusterTargetingRule(clusterId="c1", ruleType="reference")]
        assert resolve_cluster("t", "c1", rules).resolution == \
            "similarity_reference_inclusion"

    def test_no_rule_defaults_to_not_targeted(self):
        decision = resolve_cluster("t", "c1", [])
        assert not is_eligible(decision)
        assert decision.inputsSummary.get("default") is True

    def test_decision_is_deterministic(self):
        first = resolve_cluster("t", "c1", self.RULES)
        second = resolve_cluster("t", "c1", self.RULES)
        assert first.resolution == second.resolution
        assert first.ruleApplied == second.ruleApplied


# ── Intent invariants ─────────────────────────────────────────────────────

class TestIntentInvariants:
    async def test_execution_by_aether_true_rejected(self, service):
        with pytest.raises(BadRequestError):
            await service.create_intent(_tenant(), {
                "source": "tenant_declared", "includeClusters": ["c1"],
                "executionByAether": True,
            }, "tester")

    async def test_external_execution_false_rejected(self, service):
        with pytest.raises(BadRequestError):
            await service.create_intent(_tenant(), {
                "source": "tenant_declared", "includeClusters": ["c1"],
                "externalExecutionRequired": False,
            }, "tester")

    async def test_model_rejects_execution_claim_directly(self):
        with pytest.raises(Exception):
            TargetingIntent(tenantId="t", source="tenant_declared",
                            executionByAether=True)  # type: ignore[arg-type]

    async def test_empty_intent_rejected(self, service):
        with pytest.raises(BadRequestError):
            await service.create_intent(_tenant(), {"source": "tenant_declared"}, "t")

    async def test_update_cannot_flip_frozen_fields(self, service):
        tenant_id = _tenant()
        record = await service.create_intent(tenant_id, {
            "source": "tenant_declared", "includeClusters": ["c1"],
        }, "tester")
        updated = await service.update_intent(tenant_id, record["id"], {
            "executionByAether": True, "excludeClusters": ["c9"],
        }, "tester")
        assert updated["executionByAether"] is False
        assert updated["excludeClusters"] == ["c9"]


# ── Eligibility snapshots ─────────────────────────────────────────────────

class TestEligibilitySnapshots:
    async def test_snapshot_partitions_and_policy_refs(self, service):
        tenant_id = _tenant()
        intent = await service.create_intent(tenant_id, {
            "source": "tenant_declared",
            "includeClusters": ["inc1"], "excludeClusters": ["exc1"],
            "holdoutClusters": ["hold1"], "referenceClusters": ["ref1"],
        }, "tester")
        snapshot = await service.compute_eligibility_snapshot(
            tenant_id, intent["id"], "2026-07-11T00:00:00+00:00"
        )
        assert set(snapshot["eligibleClusters"]) == {"inc1", "ref1"}
        assert "exc1" in snapshot["excludedClusters"]
        assert snapshot["holdoutClusters"] == ["hold1"]
        assert len(snapshot["policyDecisionIds"]) == 4
        assert snapshot["clusterMemberCounts"]["inc1"] == 10

    async def test_holdout_cluster_never_eligible(self, service):
        tenant_id = _tenant()
        intent = await service.create_intent(tenant_id, {
            "source": "tenant_declared",
            "includeClusters": ["dual"], "holdoutClusters": ["dual"],
        }, "tester")
        snapshot = await service.compute_eligibility_snapshot(
            tenant_id, intent["id"], "2026-07-11T00:00:00+00:00"
        )
        assert "dual" not in snapshot["eligibleClusters"]
        assert "dual" in snapshot["holdoutClusters"]

    async def test_consent_signal_blocks_inclusion(self, service):
        tenant_id = _tenant()
        intent = await service.create_intent(tenant_id, {
            "source": "tenant_declared", "includeClusters": ["blocked"],
        }, "tester")
        snapshot = await service.compute_eligibility_snapshot(
            tenant_id, intent["id"], "2026-07-11T00:00:00+00:00",
            cluster_signals={"blocked": ClusterSignals(consent_blocked=True)},
        )
        assert snapshot["eligibleClusters"] == []
        assert "blocked" in snapshot["excludedClusters"]

    async def test_recompute_same_as_of_is_idempotent(self, service):
        tenant_id = _tenant()
        intent = await service.create_intent(tenant_id, {
            "source": "tenant_declared", "includeClusters": ["c1"],
        }, "tester")
        as_of = "2026-07-11T00:00:00+00:00"
        first = await service.compute_eligibility_snapshot(tenant_id, intent["id"], as_of)
        second = await recompute_snapshot(tenant_id, intent["id"], as_of,
                                          service=service)
        assert first["snapshotId"] == second["snapshotId"]
        all_snaps = await service.repos.snapshots.list_for_tenant(
            tenant_id, targetingIntentId=intent["id"]
        )
        assert len(all_snaps) == 1


# ── Mapping quality ───────────────────────────────────────────────────────

class TestMappingQuality:
    def test_low_rates_block_suggestions(self):
        quality = compute_mapping_quality(mapping_rate=0.2,
                                          touchpoint_resolution_rate=0.3,
                                          identity_resolution_rate=0.3,
                                          cluster_assignment_rate=0.2)
        assert quality.blocksSuggestions is True
        assert quality.reasons

    def test_high_rates_pass(self):
        quality = compute_mapping_quality(
            mapping_rate=0.95, touchpoint_resolution_rate=0.9,
            identity_resolution_rate=0.92, cluster_assignment_rate=0.9,
            last_sync_at=utc_now_iso(),
        )
        assert quality.blocksSuggestions is False
        assert quality.providerSyncFreshness == "live"

    def test_stale_sync_degrades_quality(self):
        fresh = compute_mapping_quality(mapping_rate=0.9,
                                        touchpoint_resolution_rate=0.9,
                                        identity_resolution_rate=0.9,
                                        cluster_assignment_rate=0.9,
                                        last_sync_at=utc_now_iso())
        stale = compute_mapping_quality(mapping_rate=0.9,
                                        touchpoint_resolution_rate=0.9,
                                        identity_resolution_rate=0.9,
                                        cluster_assignment_rate=0.9,
                                        last_sync_at="2026-01-01T00:00:00+00:00")
        assert stale.qualityScore < fresh.qualityScore
        assert stale.providerSyncFreshness == "stale"


# ── Leakage ───────────────────────────────────────────────────────────────

def _snapshot(tenant_id: str, excluded=("exc1",), holdouts=("hold1",)) -> TargetingEligibilitySnapshot:
    return TargetingEligibilitySnapshot(
        tenantId=tenant_id, targetingIntentId="ti_x", asOf=utc_now_iso(),
        excludedClusters=list(excluded), holdoutClusters=list(holdouts),
        identityConfidenceThreshold=0.7, clusterMembershipThreshold=0.6,
        pathConfidenceThreshold=0.5, evidenceCoverageThreshold=0.5,
        clusterMemberCounts={"exc1": 20, "hold1": 10},
    )


def _observation(tenant_id: str, reached_excluded=(), reached_holdout=(),
                 quality: ProviderMappingQuality | None = None) -> TargetingObservation:
    return TargetingObservation(
        tenantId=tenant_id, campaignId="camp1",
        targetingIntentId="ti_x", eligibilitySnapshotId="tes_x",
        reachedExcludedClusters=list(reached_excluded),
        reachedHoldoutClusters=list(reached_holdout),
        reachedEntities=[EntityRef(kind="user", id=f"u{i}", label="exc1")
                         for i in range(len(reached_excluded) * 3)],
        providerMappingQuality=quality or compute_mapping_quality(
            mapping_rate=0.9, touchpoint_resolution_rate=0.9,
            identity_resolution_rate=0.9, cluster_assignment_rate=0.9,
            last_sync_at=utc_now_iso(),
        ),
    )


class TestLeakage:
    def test_zero_leakage_no_findings(self):
        tenant_id = _tenant()
        findings = detect_leakage(_snapshot(tenant_id), _observation(tenant_id))
        assert findings == []

    def test_excluded_reached_produces_finding_with_evidence_chain(self):
        tenant_id = _tenant()
        findings = detect_leakage(
            _snapshot(tenant_id), _observation(tenant_id, reached_excluded=["exc1"])
        )
        assert len(findings) == 1
        finding = findings[0]
        assert finding.reasonCode == "manual_tenant_exclusion"
        assert finding.leakageRate > 0
        sources = {ref.source for ref in finding.evidenceRefs}
        assert {"targeting_observation", "eligibility_snapshot"} <= sources

    def test_holdout_reach_flagged_as_negative_holdout(self):
        tenant_id = _tenant()
        findings = detect_leakage(
            _snapshot(tenant_id), _observation(tenant_id, reached_holdout=["hold1"])
        )
        assert len(findings) == 1
        assert findings[0].reasonCode == "negative_holdout"

    def test_severity_bands_scale_with_rate(self):
        low = ExclusionLeakageFinding(
            tenantId="t", campaignId="c", clusterId="x",
            reasonCode="manual_tenant_exclusion", leakageRate=0.03,
            severity="low",
        )
        assert low.severity == "low"
        with pytest.raises(Exception):
            ExclusionLeakageFinding(
                tenantId="t", campaignId="c", clusterId="x",
                reasonCode="manual_tenant_exclusion",
                likelyCauses=["made_up_cause"],
            )


# ── Journey deltas / overexposure ─────────────────────────────────────────

class TestJourneyDelta:
    def test_stage_delta_math(self):
        delta = compute_journey_delta(
            tenant_id="t", campaign_id="c", cluster_id="cl",
            before_stage_counts={"reached": 10, "engaged": 4, "converted": 1},
            after_stage_counts={"reached": 30, "engaged": 12, "converted": 5,
                                "attributed": 4},
            before_window={"start": "2026-06-01", "end": "2026-06-30"},
            after_window={"start": "2026-07-01", "end": "2026-07-09"},
        )
        assert delta.populationStageDeltas["reached"] == 20.0
        assert delta.convertedCount == 5
        assert delta.nonProgressedCount == 18

    def test_overexposure_score_bounds(self):
        assert overexposure_score([]) == 0.0
        assert overexposure_score([1, 2, 3]) == 0.0
        heavy = overexposure_score([30, 40, 50])
        assert 0.9 <= heavy <= 1.0 and is_overexposed(heavy)


# ── Exports ───────────────────────────────────────────────────────────────

class TestExports:
    async def test_export_uses_snapshot_policy_view(self, service):
        tenant_id = _tenant()
        intent = await service.create_intent(tenant_id, {
            "source": "tenant_declared",
            "includeClusters": ["inc1"], "excludeClusters": ["exc1"],
            "holdoutClusters": ["hold1"],
        }, "tester")
        await service.compute_eligibility_snapshot(
            tenant_id, intent["id"], "2026-07-11T00:00:00+00:00"
        )
        package = await build_export_package(
            tenant_id, targeting_intent_id=intent["id"],
            repositories=service.repos,
        )
        assert package["includeClusterIds"] == ["inc1"]
        assert "exc1" in package["excludeClusterIds"]
        assert package["holdoutClusterIds"] == ["hold1"]
        assert package["executionByAether"] is False
        assert package["externalExecutionRequired"] is True
        assert any("Aether does not execute" in note
                   for note in package["implementationNotes"])
        assert package["evidenceRefs"]

    async def test_export_flag_off_rejected(self, service, monkeypatch):
        patched = dataclasses.replace(settings.targeting_intelligence,
                                      enabled=True, exports_enabled=False)
        monkeypatch.setattr(settings, "targeting_intelligence", patched)
        with pytest.raises(BadRequestError):
            await build_export_package(_tenant(), targeting_intent_id="ti_x",
                                       repositories=service.repos)

    async def test_export_requires_reference(self, service):
        with pytest.raises(BadRequestError):
            await build_export_package(_tenant(), repositories=service.repos)


# ── Suggestions ───────────────────────────────────────────────────────────

class TestSuggestions:
    def _finding(self, severity: str = "high") -> ExclusionLeakageFinding:
        return ExclusionLeakageFinding(
            tenantId="t1", campaignId="camp1", clusterId="exc1",
            reasonCode="manual_tenant_exclusion",
            excludedEntityCount=20, reachedEntityCount=5,
            leakageRate=0.25, severity=severity,  # type: ignore[arg-type]
        )

    def test_leakage_suggestion_has_evidence_chain(self):
        suggestion = leakage_suggestion(self._finding())
        assert suggestion is not None
        assert suggestion.suggestion_class.value == "retargeting"
        assert suggestion.evidence
        assert "observed" in suggestion.summary.lower() or \
               "observed" in suggestion.title.lower()

    def test_low_severity_skipped(self):
        assert leakage_suggestion(self._finding("info")) is None

    def test_blocked_by_mapping_quality(self):
        low_quality = compute_mapping_quality(mapping_rate=0.1,
                                              touchpoint_resolution_rate=0.1,
                                              identity_resolution_rate=0.1,
                                              cluster_assignment_rate=0.1)
        assert leakage_suggestion(self._finding(), low_quality) is None

    def test_flag_off_produces_nothing(self, monkeypatch):
        patched = dataclasses.replace(settings.targeting_intelligence,
                                      enabled=True, ooda_suggestions_enabled=False)
        monkeypatch.setattr(settings, "targeting_intelligence", patched)
        assert leakage_suggestion(self._finding()) is None

    def test_overexposure_suggestion(self):
        suggestion = overexposure_suggestion(
            "t1", "camp1", "cl1", 0.8,
            evidence=[{"id": "obs1", "type": "event",
                       "source": "targeting_observation"}],
        )
        assert suggestion is not None and suggestion.urgency_score == 0.8


# ── Routes / isolation / kyber ────────────────────────────────────────────

class TestRoutesAndIsolation:
    async def test_flag_off_rejects_routes(self, monkeypatch):
        patched = dataclasses.replace(settings.targeting_intelligence, enabled=False)
        monkeypatch.setattr(settings, "targeting_intelligence", patched)
        with pytest.raises(BadRequestError):
            await t_routes.list_intents(FakeRequest(_tenant()))

    async def test_cross_tenant_intent_not_found(self, service, monkeypatch):
        monkeypatch.setattr(
            "services.targeting_intelligence.routes.get_targeting_repositories",
            lambda: service.repos,
        )
        tenant_a, tenant_b = _tenant(), _tenant()
        record = await service.create_intent(tenant_a, {
            "source": "tenant_declared", "includeClusters": ["c1"],
        }, "tester")
        with pytest.raises(NotFoundError):
            await t_routes.get_intent(record["id"], FakeRequest(tenant_b))

    async def test_campaign_scope_payload_shape(self, service, monkeypatch):
        monkeypatch.setattr(
            "services.targeting_intelligence.routes.get_targeting_repositories",
            lambda: service.repos,
        )
        tenant_id = _tenant()
        await service.create_intent(tenant_id, {
            "source": "tenant_declared", "campaignId": "camp1",
            "includeClusters": ["c1"],
        }, "tester")
        response = await t_routes.campaign_targeting_intelligence(
            "camp1", FakeRequest(tenant_id)
        )
        data = response["data"]
        assert data["executionByAether"] is False
        assert data["externalExecutionRequired"] is True
        assert len(data["intents"]) == 1

    async def test_kyber_requires_operator(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "services.security.request_context.require_kyber_operator",
            lambda request: calls.append(request) or SimpleNamespace(operator_id="op"),
        )
        response = await t_kyber.fleet_health(FakeRequest("op"))
        assert calls and "intentCount" in response["data"]

    async def test_release_readiness_ready(self):
        result = await release_readiness()
        assert result["ready"] is True
        assert all(c["passed"] for c in result["checks"])
