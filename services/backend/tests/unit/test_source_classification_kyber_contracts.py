"""Kyber registration and enqueue contracts for source-classification repair."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.jobs.handlers import HANDLER_REGISTRY, TENANT_INVOCABLE, unregister_handler
from services.measurement.routes import kyber
from services.traffic.classifier import SOURCE_CLASSIFIER_VERSION
from services.traffic.repair import (
    JOB_TYPE,
    register_source_classification_repair_handler,
)


def _request(tenant_id: str = "tenant-a") -> SimpleNamespace:
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        actor_id="operator-1",
        subject="operator-1",
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


def test_kyber_router_registers_health_and_reclassification_contracts() -> None:
    route_methods = {
        (route.path, method)
        for route in kyber.router.routes
        for method in (route.methods or set())
    }

    assert (
        "/v1/kyber/measurement/source-classification/health",
        "GET",
    ) in route_methods
    assert (
        "/v1/kyber/measurement/source-classification/reclassify",
        "POST",
    ) in route_methods
    assert (
        "/v1/kyber/measurement/source-classification/operations",
        "GET",
    ) in route_methods
    assert kyber.router.dependencies, "Kyber router must retain operator auth dependency"


# Stable operator-operations contract (a frontend agent renders these keys).
_OPERATIONS_KEYS = {
    "tenant_id",
    "window",
    "totals",
    "classification_by_source_class",
    "classification_by_proof_level",
    "direct_unknown_rate",
    "evidence_conflict_count",
    "invalid_source_link_count",
    "source_link_replay_count",
    "handoff_correlation",
    "install_referrer_retrieval",
    "universal_link_processing_count",
    "deferred_attribution",
    "adattributionkit_ingestion_count",
    "sdk_deep_link_parse_failures",
    "reclassification_jobs",
    "utm_inconsistency_rate",
    "classification_drift",
}


@pytest.mark.asyncio
async def test_operations_endpoint_returns_zeroed_structure_for_empty_tenant() -> None:
    from services.measurement.repositories import touchpoint_repo as tr

    tr._local_store.clear()
    response = await kyber.source_classification_operations(
        _request("empty-tenant"), start=None, end=None, platform=None, sdk=None
    )
    data = response["data"]
    assert set(data.keys()) == _OPERATIONS_KEYS
    assert data["tenant_id"] == "empty-tenant"
    assert data["totals"] == {
        "touchpoints": 0,
        "attribution_eligible": 0,
        "machine_excluded": 0,
    }
    assert data["direct_unknown_rate"] == 0.0
    assert data["handoff_correlation"] == {"success": 0, "expired": 0, "failed": 0}
    assert data["deferred_attribution"] == {"resolved": 0, "unmatched": 0, "expired": 0}
    assert data["reclassification_jobs"] == {"running": 0, "failed": 0, "completed": 0}
    assert data["classification_drift"]["legacy_vs_canonical_divergence_rate"] == 0.0


@pytest.mark.asyncio
async def test_operations_endpoint_aggregates_populated_tenant() -> None:
    from services.measurement.repositories import touchpoint_repo as tr

    tr._local_store.clear()
    tr._local_store["k1"] = {
        "tenant_id": "tenant-a", "privacy_class": "active",
        "source_class": "direct_unknown", "proof_level": "none",
        "attribution_eligible": True, "occurred_at": "2026-07-10T00:00:00+00:00",
        "entry_method": "ios_universal_link",
    }
    tr._local_store["k2"] = {
        "tenant_id": "tenant-a", "privacy_class": "active",
        "source_class": "paid_search", "proof_level": "declared",
        "attribution_eligible": False, "actor_type": "machine",
        "occurred_at": "2026-07-11T00:00:00+00:00",
        "evidence_conflicts": ["utm_vs_clickid"], "verified_referral_link_id": "v1",
    }
    try:
        response = await kyber.source_classification_operations(
            _request("tenant-a"), start=None, end=None, platform=None, sdk=None
        )
    finally:
        tr._local_store.clear()

    data = response["data"]
    assert set(data.keys()) == _OPERATIONS_KEYS
    assert data["totals"] == {
        "touchpoints": 2,
        "attribution_eligible": 1,
        "machine_excluded": 1,
    }
    assert data["classification_by_source_class"] == {"direct_unknown": 1, "paid_search": 1}
    assert data["classification_by_proof_level"] == {"none": 1, "declared": 1}
    assert data["direct_unknown_rate"] == 0.5
    assert data["evidence_conflict_count"] == 1
    assert data["universal_link_processing_count"] == 1
    assert data["handoff_correlation"]["success"] == 1
    assert data["utm_inconsistency_rate"] == 0.5


@pytest.mark.asyncio
async def test_operations_endpoint_rejects_inverted_window() -> None:
    from shared.common.common import BadRequestError

    with pytest.raises(BadRequestError):
        await kyber.source_classification_operations(
            _request("tenant-a"),
            start="2026-07-31T00:00:00Z",
            end="2026-07-01T00:00:00Z",
            platform=None,
            sdk=None,
        )


def test_main_mounts_kyber_router_and_registers_repair_handler_at_startup() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    main_source = (backend_root / "main.py").read_text(encoding="utf-8")

    assert "from services.measurement.routes.kyber import router as measurement_kyber_router" in main_source
    assert "app.include_router(measurement_kyber_router)" in main_source
    assert "from services.traffic.repair import register_source_classification_repair_handler" in main_source
    assert "register_source_classification_repair_handler()" in main_source


def test_repair_job_is_internal_only_and_registration_is_idempotent() -> None:
    existed = JOB_TYPE in HANDLER_REGISTRY
    register_source_classification_repair_handler()
    first_handler = HANDLER_REGISTRY[JOB_TYPE]
    register_source_classification_repair_handler()

    assert HANDLER_REGISTRY[JOB_TYPE] is first_handler
    assert JOB_TYPE not in TENANT_INVOCABLE

    if not existed:
        unregister_handler(JOB_TYPE)


@pytest.mark.asyncio
async def test_health_endpoint_returns_tenant_scoped_classifier_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        source_classification_health=AsyncMock(
            return_value={
                "summary": {"total": 2, "classified": 2},
                "versions": [{"name": SOURCE_CLASSIFIER_VERSION, "count": 2}],
                "providers": [{"name": "openai", "count": 2}],
                "mediation": [],
                "source_classes": [{"name": "organic_search", "count": 2}],
                "economic_classes": [{"name": "unpaid", "count": 2}],
                "channel_families": [{"name": "search", "count": 2}],
                "proof_levels": [{"name": "domain_verified", "count": 2}],
            }
        )
    )
    monkeypatch.setattr(kyber, "_touchpoint_repo", repo)

    response = await kyber.source_classification_health(_request())

    repo.source_classification_health.assert_awaited_once_with("tenant-a")
    assert response["data"]["target_classifier_version"] == SOURCE_CLASSIFIER_VERSION
    assert response["data"]["status"] == "healthy"
    assert response["data"]["summary"]["total"] == 2
    # Canonical dimension breakdowns are part of the Kyber health contract.
    assert response["data"]["source_classes"] == [{"name": "organic_search", "count": 2}]
    assert response["data"]["economic_classes"] == [{"name": "unpaid", "count": 2}]
    assert response["data"]["channel_families"] == [{"name": "search", "count": 2}]
    assert response["data"]["proof_levels"] == [{"name": "domain_verified", "count": 2}]


@pytest.mark.asyncio
async def test_health_endpoint_reports_degraded_for_unclassified_or_outdated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SimpleNamespace(
        source_classification_health=AsyncMock(
            return_value={
                "summary": {"total": 4, "classified": 3, "unclassified": 1},
                "versions": [
                    {"name": SOURCE_CLASSIFIER_VERSION, "count": 2},
                    {"name": "1.0", "count": 1},
                    {"name": "unclassified", "count": 1},
                ],
                "providers": [],
                "mediation": [],
            }
        )
    )
    monkeypatch.setattr(kyber, "_touchpoint_repo", repo)

    response = await kyber.source_classification_health(_request())

    assert response["data"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_reclassify_endpoint_replays_a_caller_stable_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = SimpleNamespace(
        enqueue=AsyncMock(
            return_value={"id": "job-1", "status": "queued", "replayed": False}
        )
    )
    monkeypatch.setattr(kyber, "get_jobs_service", lambda: jobs)
    body = kyber.SourceClassificationRepairRequest(
        start_date="2026-07-01",
        end_date="2026-07-31",
        dry_run=False,
        limit=500,
        request_id="kyber-request-0001",
    )

    first = await kyber.reclassify_sources(_request(), body)
    second = await kyber.reclassify_sources(_request(), body)

    assert jobs.enqueue.await_count == 2
    first_call, second_call = jobs.enqueue.await_args_list
    assert first_call.args[:3] == (
        "tenant-a",
        JOB_TYPE,
        {
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "dry_run": False,
            "limit": 500,
            "request_id": "kyber-request-0001",
        },
    )
    assert first_call.kwargs["idempotency_key"] == second_call.kwargs["idempotency_key"]
    assert first_call.kwargs["idempotency_key"].startswith("source-classification:")
    assert first_call.kwargs["requested_by"] == "operator-1"
    assert first_call.kwargs["max_attempts"] == 3
    assert first["data"]["job_id"] == "job-1"
    assert first["data"]["request_id"] == "kyber-request-0001"
    assert second["data"]["target_classifier_version"] == SOURCE_CLASSIFIER_VERSION
