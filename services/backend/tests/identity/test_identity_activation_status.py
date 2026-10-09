"""Activation dashboard status is derived from tenant-owned durable state."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime, timezone

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from config.settings import settings  # noqa: E402
from repositories.imports_repo import ImportsRepository  # noqa: E402
from repositories.jobs_repo import reset_jobs_memory  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.sdk_heartbeat_status import (  # noqa: E402
    get_sdk_heartbeat_status_repository,
    reset_sdk_heartbeat_status_memory,
)
from services.identity.explainability import AdminIdentityService  # noqa: E402
from services.identity.models import SourceIdentityRecord  # noqa: E402
from services.identity.pending_review import PendingIdentityReviewRepository  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.jobs.service import get_jobs_service  # noqa: E402
from services.projections.projection_restatement_orchestrator import (  # noqa: E402
    PROJECTION_RESTATEMENT_JOB_TYPE,
)


TENANT = "activation-tenant"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    reset_jobs_memory()
    reset_sdk_heartbeat_status_memory()
    import services.jobs.service as jobs_service_module

    jobs_service_module._service = None
    yield
    jobs_service_module._service = None


def _source(tenant_id: str, source_kind: str, suffix: str) -> SourceIdentityRecord:
    now = datetime.now(timezone.utc).isoformat()
    return SourceIdentityRecord(
        id=f"source-{suffix}",
        tenant_id=tenant_id,
        source_system_id=f"system-{suffix}",
        source_kind=source_kind,
        source_namespace=f"namespace-{suffix}",
        external_id=f"external-{suffix}",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
        first_seen_at=now,
    )


@pytest.fixture
def enabled_flags(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        projection_restatement_enabled=True,
        sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=True,
        multi_sdk_stitching_enabled=True,
        connector_backfill_enabled=True,
        campaign_restatement_enabled=True,
        value_restatement_enabled=True,
    ))


@pytest.mark.asyncio
async def test_empty_tenant_does_not_infer_sdk_or_active_projections(enabled_flags):
    result = await AdminIdentityService(repo=IdentityResolutionRepository()).activation_status(TENANT)

    assert result["historical_data_status"] == "empty"
    assert result["sdk_status"] == "not_connected"
    assert result["sdk_last_seen_at"] is None
    assert result["projection_restatement_status"] == "idle"
    assert result["projection_restatement_counts"] == {}
    assert result["pending_review_counts"]["open"] == 0
    assert result["runtime_flags"]["sdk_late_binding_enabled"] is True
    computed_at = datetime.fromisoformat(result["computed_at"])
    assert computed_at.tzinfo is not None


@pytest.mark.asyncio
async def test_historical_import_first_then_sdk_heartbeat_updates_status(enabled_flags):
    imports = ImportsRepository()
    session = await imports.create_session(TENANT, source_kind="file_upload")
    await imports.set_status(TENANT, session["id"], "committed")
    await imports.create_commit(TENANT, session["id"], {
        "status": "committed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    repo = IdentityResolutionRepository()
    await repo.create_source_identity(_source(TENANT, "csv", "csv-1"))
    service = AdminIdentityService(repo=repo)

    before_sdk = await service.activation_status(TENANT)
    assert before_sdk["historical_data_status"] == "available"
    assert before_sdk["resolution_counts"]["historical_imports"] == 1
    assert before_sdk["sdk_status"] == "not_connected"

    # Persisted aliases alone are not evidence of a live SDK connection.
    await repo.create_source_identity(_source(TENANT, "web_sdk", "sdk-1"))
    still_offline = await service.activation_status(TENANT)
    assert still_offline["sdk_status"] == "not_connected"

    await get_sdk_heartbeat_status_repository().record(
        tenant_id=TENANT,
        sdk_name="aether-web",
        tenant_app_key="app-key-redacted",
        sdk_version="1.2.3",
    )
    after_heartbeat = await service.activation_status(TENANT)
    assert after_heartbeat["sdk_status"] == "connected"
    assert after_heartbeat["sdk_last_seen_at"]
    assert after_heartbeat["historical_data_status"] == "available"


@pytest.mark.asyncio
async def test_review_recovery_and_restatement_job_states_are_visible(enabled_flags):
    reviews = PendingIdentityReviewRepository()
    candidate = await reviews.upsert_candidate(
        tenant_id=TENANT,
        identify_source_identity_id="sdk-source",
        candidate_source_identity_ids=["import-source"],
        reason_codes=["ambiguous_identity_evidence"],
        evidence=[],
    )
    await reviews.set_disposition(
        tenant_id=TENANT,
        record_id=candidate["id"],
        status="approval_recovery_required",
        reason_codes=["merge_committed_recovery_required"],
    )
    queued = await get_jobs_service().enqueue(
        TENANT,
        PROJECTION_RESTATEMENT_JOB_TYPE,
        {"restatement": {"id": "restatement-a"}},
        idempotency_key="activation-restatement",
    )

    result = await AdminIdentityService(repo=IdentityResolutionRepository()).activation_status(TENANT)

    assert result["pending_review_counts"]["approval_recovery_required"] == 1
    assert result["projection_restatement_status"] == "in_progress"
    assert result["projection_restatement_counts"][queued["status"]] == 1


@pytest.mark.asyncio
async def test_activation_state_is_tenant_scoped(enabled_flags):
    repo = IdentityResolutionRepository()
    other = "other-activation-tenant"
    await repo.create_source_identity(_source(other, "mobile_sdk", "other-sdk"))
    await get_sdk_heartbeat_status_repository().record(
        tenant_id=other,
        sdk_name="aether-mobile",
        tenant_app_key="other-app-key",
        sdk_version="1.0.0",
    )
    await ImportsRepository().create_session(other, source_kind="file_upload")
    await get_jobs_service().enqueue(
        other,
        PROJECTION_RESTATEMENT_JOB_TYPE,
        {"restatement": {"id": "other-restatement"}},
        idempotency_key="other-activation-restatement",
    )
    await PendingIdentityReviewRepository().upsert_candidate(
        tenant_id=other,
        identify_source_identity_id="other-sdk-source",
        candidate_source_identity_ids=["other-import-source"],
        reason_codes=["ambiguous_identity_evidence"],
        evidence=[],
    )

    result = await AdminIdentityService(repo=repo).activation_status(TENANT)

    assert result["historical_data_status"] == "empty"
    assert result["sdk_status"] == "not_connected"
    assert result["projection_restatement_status"] == "idle"
    assert result["projection_restatement_counts"] == {}
    assert result["pending_review_counts"]["open"] == 0


@pytest.mark.asyncio
async def test_activation_api_returns_typed_persisted_status(enabled_flags, monkeypatch):
    from starlette.requests import Request

    from services.identity import routes

    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, activation_dashboard_enabled=True
    ))

    class Tenant:
        tenant_id = TENANT

        def require_permission(self, permission):
            assert permission == "read"

    request = Request({"type": "http", "headers": [], "state": {}})
    request.state.tenant = Tenant()
    result = await routes.admin_activation_status(
        request, AdminIdentityService(repo=IdentityResolutionRepository())
    )

    data = result["data"]
    assert data["tenant_id"] == TENANT
    assert data["historical_data_status"] == "empty"
    assert data["sdk_status"] == "not_connected"
    assert data["projection_restatement_status"] == "idle"
    assert data["runtime_flags"]["projection_restatement_enabled"] is True
    assert datetime.fromisoformat(data["computed_at"]).tzinfo is not None


@pytest.mark.asyncio
async def test_conflict_counts_follow_tenant_scoped_status_transitions(enabled_flags):
    repo = IdentityResolutionRepository()
    resolved = await repo.create_conflict(
        TENANT, ["entity-a", "entity-b"], [], "contradictory_identifiers",
        0.72, ["conflicting_identity_evidence"],
    )
    await repo.resolve_conflict(resolved["id"], "operator-a", TENANT)
    dismissed = await repo.create_conflict(
        TENANT, ["entity-c", "entity-d"], [], "shared_device",
        0.51, ["shared_device"],
    )
    dismissed["status"] = "dismissed"
    await repo._conflicts.update(dismissed["id"], dismissed)
    await repo.create_conflict(
        TENANT, ["entity-e", "entity-f"], [], "contradictory_identifiers",
        0.81, ["conflicting_identity_evidence"],
    )

    other = await repo.create_conflict(
        "other-activation-tenant", ["entity-x", "entity-y"], [],
        "contradictory_identifiers", 0.89, ["conflicting_identity_evidence"],
    )
    await repo.resolve_conflict(other["id"], "operator-other", "other-activation-tenant")

    result = await AdminIdentityService(repo=repo).activation_status(TENANT)

    assert result["conflict_counts"] == {"open": 1, "resolved": 1, "dismissed": 1}
