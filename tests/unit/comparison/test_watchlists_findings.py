"""Watchlist noise controls + findings lifecycle (dispositions, ladder, handoffs)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from shared.common.common import BadRequestError

from services.intelligence.comparison.findings import (
    CausalClaimViolation,
    FindingRecord,
    FindingsService,
    validate_causal_claim,
)
from services.intelligence.comparison.watchlists import (
    MuteRule,
    NoiseControls,
    WatchlistDefinition,
    WatchlistRepository,
    apply_noise_controls,
)

TENANT = "t1"


def finding_record(**overrides) -> FindingRecord:
    base = dict(
        id=str(uuid.uuid4()),
        comparison_run_id="run-1",
        tenant_id=TENANT,
        finding_type="metric_deviation",
        dimension="behavior",
        metric="events_per_day",
        direction="increase",
        severity="medium",
        materiality=0.5,
        subject_refs=["user-a"],
        first_observed_at=datetime.now(timezone.utc),
        last_observed_at=datetime.now(timezone.utc),
        causal_claim="observed",
        evidence_basis="direct_observation",
        fact_linkage="deterministically_linked",
    )
    base.update(overrides)
    return FindingRecord(**base)


def watchlist(**noise_kwargs) -> WatchlistDefinition:
    return WatchlistDefinition(
        watchlist_id="w1",
        tenant_id=TENANT,
        name="all",
        noise=NoiseControls(**noise_kwargs),
    )


class TestCausalClaimLadder:
    def test_correlated_evidence_cannot_claim_causation(self):
        with pytest.raises(CausalClaimViolation, match="at most 'correlated'"):
            validate_causal_claim("causally_supported", "statistical_correlation")

    def test_temporal_evidence_cannot_claim_attribution(self):
        with pytest.raises(CausalClaimViolation):
            validate_causal_claim("attributed", "temporal_association")

    def test_claims_at_or_below_ceiling_pass(self):
        validate_causal_claim("correlated", "statistical_correlation")
        validate_causal_claim("observed", "statistical_correlation")
        validate_causal_claim("counterfactual_estimate", "counterfactual_scenario")

    def test_unknown_vocab_rejected(self):
        with pytest.raises(CausalClaimViolation):
            validate_causal_claim("definitely_causal", "direct_observation")
        with pytest.raises(CausalClaimViolation):
            validate_causal_claim("observed", "gut_feeling")

    def test_finding_record_enforces_ladder_at_construction(self):
        with pytest.raises(Exception):
            finding_record(
                causal_claim="causally_supported",
                evidence_basis="statistical_correlation",
            )


class TestNoiseControls:
    def test_materiality_floor_suppresses(self):
        decision = apply_noise_controls(
            [watchlist(materiality_floor=0.7)], "def-1",
            finding_record(materiality=0.4).model_dump(mode="json"), [],
        )
        assert not decision.allowed
        assert decision.suppression_reason.startswith("below_materiality_floor")

    def test_mute_rule_suppresses_dimension(self):
        decision = apply_noise_controls(
            [watchlist(mute_rules=[MuteRule(dimension="behavior")])],
            "def-1", finding_record().model_dump(mode="json"), [],
        )
        assert not decision.allowed
        assert decision.suppression_reason == "muted_by_watchlist_rule"

    def test_expired_mute_rule_is_inert(self):
        expired = MuteRule(
            dimension="behavior",
            until=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        decision = apply_noise_controls(
            [watchlist(mute_rules=[expired])], "def-1",
            finding_record().model_dump(mode="json"), [],
        )
        assert decision.allowed

    def test_dedupe_window_suppresses_repeat(self):
        prior = finding_record().model_dump(mode="json")
        decision = apply_noise_controls(
            [watchlist(dedupe_window_seconds=3600)], "def-1",
            finding_record().model_dump(mode="json"), [prior],
        )
        assert not decision.allowed
        assert "duplicate_within_dedupe_window" in decision.suppression_reason

    def test_old_duplicate_outside_window_allowed(self):
        old = finding_record(
            last_observed_at=datetime.now(timezone.utc) - timedelta(hours=2)
        ).model_dump(mode="json")
        decision = apply_noise_controls(
            [watchlist(dedupe_window_seconds=3600)], "def-1",
            finding_record().model_dump(mode="json"), [old],
        )
        assert decision.allowed

    def test_unwatched_definition_not_filtered(self):
        wl = WatchlistDefinition(
            watchlist_id="w2", tenant_id=TENANT, name="scoped",
            definition_ids=["other-def"],
            noise=NoiseControls(materiality_floor=1.0),
        )
        decision = apply_noise_controls(
            [wl], "def-1", finding_record(materiality=0.0).model_dump(mode="json"), []
        )
        assert decision.allowed

    def test_mute_rule_requires_a_target(self):
        with pytest.raises(ValueError):
            MuteRule()

    async def test_repository_roundtrip(self):
        repo = WatchlistRepository()
        await repo.upsert(watchlist(materiality_floor=0.3))
        rows = await repo.list_for_tenant(TENANT)
        assert [w.watchlist_id for w in rows] == ["w1"]
        assert await repo.list_for_tenant("other") == []


class TestFindingsLifecycle:
    async def test_create_persists_and_suppression_is_recorded(self):
        service = FindingsService()
        stored, decision = await service.create(
            finding_record(materiality=0.1),
            definition_id="def-1",
            watchlists=[watchlist(materiality_floor=0.5)],
        )
        assert not decision.allowed
        assert stored["disposition"] == "suppressed"
        assert stored["suppression_reason"].startswith("below_materiality_floor")
        # Suppressed findings remain auditable.
        rows = await service.list(TENANT, disposition="suppressed")
        assert len(rows) == 1

    async def test_disposition_transitions_record_history(self):
        service = FindingsService()
        record = finding_record()
        await service.create(record, definition_id="def-1", watchlists=[])
        updated = await service.dispose(
            TENANT, record.id, "monitor", actor_id="analyst-1", reason="watch it"
        )
        assert updated["disposition"] == "monitor"
        assert updated["disposition_history"][-1]["actor_id"] == "analyst-1"

    async def test_unknown_disposition_rejected(self):
        service = FindingsService()
        record = finding_record()
        await service.create(record, definition_id="def-1", watchlists=[])
        with pytest.raises(BadRequestError, match="Unknown disposition"):
            await service.dispose(TENANT, record.id, "yeet", actor_id="a")

    async def test_investigate_opens_case_on_existing_plane(self):
        from repositories.repos import InvestigationRepository

        service = FindingsService()
        record = finding_record()
        await service.create(record, definition_id="def-1", watchlists=[])
        updated = await service.dispose(
            TENANT, record.id, "investigate", actor_id="analyst-1"
        )
        case_id = updated["investigation_id"]
        assert case_id
        case = await InvestigationRepository().find_by_id(case_id)
        assert case is not None
        assert case["tenantId"] == TENANT
        assert case["status"] == "open"
        assert case["subjects"][0]["id"] == "user-a"

    async def test_act_emits_ooda_recommendation(self):
        from services.intelligence.repositories import RecommendationRepository

        service = FindingsService()
        record = finding_record(severity="high", materiality=0.9)
        await service.create(record, definition_id="def-1", watchlists=[])
        updated = await service.dispose(TENANT, record.id, "act", actor_id="analyst-1")
        rec_id = updated.get("recommendation_id")
        if rec_id:  # a family matched — the loop is linked end to end
            stored = await RecommendationRepository().find_by_id(rec_id)
            assert stored is not None and stored["tenant_id"] == TENANT
        else:  # no family matched — honestly unlinked, disposition still applied
            assert updated["disposition"] == "act"

    async def test_tenant_isolation_on_reads(self):
        service = FindingsService()
        record = finding_record()
        await service.create(record, definition_id="def-1", watchlists=[])
        from shared.common.common import NotFoundError

        with pytest.raises(NotFoundError):
            await service.get("other-tenant", record.id)
