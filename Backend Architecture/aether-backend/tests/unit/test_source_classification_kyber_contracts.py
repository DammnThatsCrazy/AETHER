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
    assert kyber.router.dependencies, "Kyber router must retain operator auth dependency"


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
