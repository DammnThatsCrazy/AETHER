"""Repair orchestration contracts over the existing journey/attribution planes."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from services.traffic.classifier import SOURCE_CLASSIFIER_VERSION, SourceClassifier
from services.traffic.repair import (
    SourceClassificationRepairService,
    _reset_local_repair_runs,
)


@pytest.fixture(autouse=True)
def local_repair_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr("services.traffic.repair.get_pool", no_pool)
    _reset_local_repair_runs()
    yield
    _reset_local_repair_runs()


def _historical_touchpoint() -> dict:
    return {
        "tenant_id": "tenant-a",
        "touchpoint_id": str(uuid4()),
        "profile_id": "profile-1",
        "occurred_at": "2026-07-01T12:30:00Z",
        "referrer": "https://chatgpt.com/",
        "normalized_referrer_domain": "chatgpt.com",
        "referrer_path_hash": "existing-one-way-path-fingerprint",
        "source": "chatgpt.com",
        "medium": "referral",
        "channel": "referral",
        "source_class": "external_referral",
        "referral_mediation_type": "unknown_external_referral",
        "actor_type": "human",
        "journey_role": "discovery",
        "verification_level": "inferred",
        "source_classifier_version": "1.0",
        "attribution_eligible": True,
        "source_classification_evidence": {},
    }


def _service(row: dict) -> tuple[SourceClassificationRepairService, SimpleNamespace]:
    touchpoints = SimpleNamespace(
        list_for_source_reclassification=AsyncMock(return_value=[row]),
        apply_source_classification=AsyncMock(return_value=row),
    )
    conversions = SimpleNamespace(list_by_profile=AsyncMock(return_value=[]))
    compiler = SimpleNamespace(compile_for_profile=AsyncMock(return_value={}))
    attribution = SimpleNamespace(run_for_conversion=AsyncMock(return_value={}))
    service = SourceClassificationRepairService.__new__(SourceClassificationRepairService)
    service._touchpoints = touchpoints
    service._conversions = conversions
    service._compiler = compiler
    service._attribution = attribution
    service._classifier = SourceClassifier()
    return service, SimpleNamespace(
        touchpoints=touchpoints,
        conversions=conversions,
        compiler=compiler,
        attribution=attribution,
    )


@pytest.mark.asyncio
async def test_dry_run_classifies_without_mutation_or_downstream_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _historical_touchpoint()
    service, fakes = _service(row)
    backfill = AsyncMock()
    monkeypatch.setattr("services.traffic.repair.backfill_tenant", backfill)

    result = await service.run(
        "tenant-a",
        "job-dry-run",
        {"dry_run": True, "limit": 10, "page_size": 10},
    )

    assert result["status"] == "succeeded"
    assert result["dry_run"] is True
    assert result["counters"]["scanned"] == 1
    assert result["counters"]["reclassified"] == 1
    fakes.touchpoints.apply_source_classification.assert_not_awaited()
    fakes.compiler.compile_for_profile.assert_not_awaited()
    fakes.conversions.list_by_profile.assert_not_awaited()
    fakes.attribution.run_for_conversion.assert_not_awaited()
    backfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_repair_forces_rebuild_recompute_and_measurement_restatement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _historical_touchpoint()
    service, fakes = _service(row)
    conversion_id = str(uuid4())
    fakes.conversions.list_by_profile.return_value = [
        {"conversion_id": conversion_id}
    ]
    backfill_result = SimpleNamespace(
        campaign_perf_rows=3,
        journey_econ_rows=2,
        attribution_credit_rows=4,
        errors=[],
    )
    backfill = AsyncMock(return_value=backfill_result)
    monkeypatch.setattr("services.traffic.repair.backfill_tenant", backfill)

    result = await service.run(
        "tenant-a",
        "job-live-run",
        {
            "dry_run": False,
            "limit": 10,
            "page_size": 10,
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
        },
    )

    assert result["status"] == "succeeded"
    assert result["counters"]["journeys_rebuilt"] == 1
    assert result["counters"]["conversions_recomputed"] == 1
    assert result["counters"]["gold_rows"] == 9

    apply_call = fakes.touchpoints.apply_source_classification.await_args
    assert apply_call.args[:2] == ("tenant-a", row["touchpoint_id"])
    applied = apply_call.args[2]
    assert applied["ai_provider"] == "openai"
    assert applied["ai_product"] == "chatgpt"
    assert applied["referrer_path_hash"] == "existing-one-way-path-fingerprint"
    assert apply_call.kwargs["reason"] == (
        f"historical_reclassification:{SOURCE_CLASSIFIER_VERSION}"
    )
    assert apply_call.kwargs["job_id"] == "job-live-run"

    fakes.compiler.compile_for_profile.assert_awaited_once_with(
        "tenant-a",
        "profile-1",
        identity_type="profile",
        trigger_reason=f"source_classifier:{SOURCE_CLASSIFIER_VERSION}",
    )
    fakes.conversions.list_by_profile.assert_awaited_once_with(
        "tenant-a",
        "profile-1",
        identity_type="profile",
        attribution_eligible_only=True,
        limit=10000,
    )
    fakes.attribution.run_for_conversion.assert_awaited_once_with(
        "tenant-a",
        conversion_id,
        trigger_reason=f"source_classifier:{SOURCE_CLASSIFIER_VERSION}",
        source_classifier_version=SOURCE_CLASSIFIER_VERSION,
    )
    assert backfill.await_args.args == (
        "tenant-a",
        date(2026, 7, 1),
        date(2026, 7, 1),
    )
    reason = backfill.await_args.kwargs["restatement_reason"]
    assert "source classification repair" in reason
    assert SOURCE_CLASSIFIER_VERSION in reason


def test_repair_replays_privacy_safe_user_agent_signature() -> None:
    classifier = SourceClassifier()
    original = classifier.classify(user_agent="Mozilla/5.0 GPTBot/1.2")
    service = SourceClassificationRepairService.__new__(
        SourceClassificationRepairService
    )
    service._classifier = classifier

    repaired = service._classify_row(
        {
            "source_classification_evidence": original.evidence_payload(),
            "actor_type": original.actor_type,
        }
    )

    assert repaired.source_class == "machine_referral"
    assert repaired.referral_mediation_type == "crawler_discovery"
    assert repaired.actor_type == "machine"
    assert repaired.journey_role == "excluded"
    assert repaired.attribution_eligible is False


@pytest.mark.asyncio
async def test_cluster_identity_rebuild_and_conversion_date_expand_restatement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        **_historical_touchpoint(),
        "profile_id": None,
        "cluster_id": "cluster-1",
    }
    service, fakes = _service(row)
    conversion_id = str(uuid4())
    fakes.conversions.list_by_profile.return_value = [
        {
            "conversion_id": conversion_id,
            "occurred_at": "2026-07-10T18:00:00Z",
        }
    ]
    backfill = AsyncMock(
        return_value=SimpleNamespace(
            campaign_perf_rows=1,
            journey_econ_rows=1,
            attribution_credit_rows=1,
            errors=[],
        )
    )
    monkeypatch.setattr("services.traffic.repair.backfill_tenant", backfill)

    await service.run(
        "tenant-a",
        "job-cluster",
        {
            "dry_run": False,
            "limit": 10,
            "page_size": 10,
            "start_date": "2026-07-01",
            "end_date": "2026-07-01",
        },
    )

    fakes.compiler.compile_for_profile.assert_awaited_once_with(
        "tenant-a",
        "cluster-1",
        identity_type="cluster",
        trigger_reason=f"source_classifier:{SOURCE_CLASSIFIER_VERSION}",
    )
    fakes.conversions.list_by_profile.assert_awaited_once_with(
        "tenant-a",
        "cluster-1",
        identity_type="cluster",
        attribution_eligible_only=True,
        limit=10000,
    )
    assert backfill.await_args.args[1:] == (
        date(2026, 7, 1),
        date(2026, 7, 10),
    )


def _backfill_result() -> SimpleNamespace:
    return SimpleNamespace(
        campaign_perf_rows=1,
        journey_econ_rows=1,
        attribution_credit_rows=1,
        errors=[],
    )


@pytest.mark.asyncio
async def test_failed_journey_is_not_checkpointed_and_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fakes = _service(_historical_touchpoint())
    fakes.compiler.compile_for_profile.side_effect = [
        RuntimeError("temporary compiler failure"),
        {},
    ]
    backfill = AsyncMock(return_value=_backfill_result())
    monkeypatch.setattr("services.traffic.repair.backfill_tenant", backfill)
    payload = {"dry_run": False, "limit": 10, "page_size": 10}

    with pytest.raises(RuntimeError, match="journey rebuild work remains"):
        await service.run("tenant-a", "job-retry-journey", payload)

    result = await service.run("tenant-a", "job-retry-journey", payload)

    assert fakes.compiler.compile_for_profile.await_count == 2
    fakes.conversions.list_by_profile.assert_awaited_once()
    fakes.touchpoints.apply_source_classification.assert_awaited_once()
    assert result["counters"]["journeys_rebuilt"] == 1
    assert result["counters"]["rebuilt_identity_keys"] == ["profile:profile-1"]
    assert result["status"] == "succeeded"
    assert result["errors"] == []
    backfill.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_conversion_is_not_checkpointed_and_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fakes = _service(_historical_touchpoint())
    conversion_id = str(uuid4())
    fakes.conversions.list_by_profile.return_value = [
        {"conversion_id": conversion_id}
    ]
    fakes.attribution.run_for_conversion.side_effect = [
        RuntimeError("temporary attribution failure"),
        {},
    ]
    backfill = AsyncMock(return_value=_backfill_result())
    monkeypatch.setattr("services.traffic.repair.backfill_tenant", backfill)
    payload = {"dry_run": False, "limit": 10, "page_size": 10}

    with pytest.raises(RuntimeError, match="attribution recomputation work remains"):
        await service.run("tenant-a", "job-retry-attribution", payload)

    result = await service.run("tenant-a", "job-retry-attribution", payload)

    fakes.compiler.compile_for_profile.assert_awaited_once()
    fakes.conversions.list_by_profile.assert_awaited_once()
    assert fakes.attribution.run_for_conversion.await_count == 2
    assert result["counters"]["conversions_recomputed"] == 1
    assert result["counters"]["recomputed_conversion_ids"] == [conversion_id]
    assert result["status"] == "succeeded"
    assert result["errors"] == []
    backfill.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_restatement_keeps_phase_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, fakes = _service(_historical_touchpoint())
    backfill = AsyncMock(
        side_effect=[RuntimeError("warehouse unavailable"), _backfill_result()]
    )
    monkeypatch.setattr("services.traffic.repair.backfill_tenant", backfill)
    payload = {"dry_run": False, "limit": 10, "page_size": 10}

    with pytest.raises(RuntimeError, match="warehouse unavailable"):
        await service.run("tenant-a", "job-retry-restatement", payload)

    result = await service.run("tenant-a", "job-retry-restatement", payload)

    fakes.compiler.compile_for_profile.assert_awaited_once()
    fakes.conversions.list_by_profile.assert_awaited_once()
    assert backfill.await_count == 2
    assert result["counters"]["gold_rows"] == 3
    assert result["status"] == "succeeded"
    assert result["errors"] == []
