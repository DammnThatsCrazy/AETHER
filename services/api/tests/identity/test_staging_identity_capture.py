from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from config import settings as settings_module
from identity.identity import staging_capture, staging_capture_routes
from identity.identity.scenario_evidence import (
    IDENTITY_CONTINUITY_SCENARIOS,
    IdentityScenarioEvidenceRepository,
    ScenarioExecutionRequest,
    reset_identity_scenario_evidence_memory,
)


class _Repo:
    async def get_identity_health(self, tenant_id):
        assert tenant_id == "tenant-a"
        return {"total_subjects": 2, "total_entities": 2, "total_aliases": 3, "open_conflicts": 1, "recent_merges": 1, "recent_splits": 0, "tenant_id": tenant_id}

    async def get_recent_merges(self, tenant_id, limit):
        assert tenant_id == "tenant-a"
        return [{"id": "merge-1", "tenant_id": tenant_id, "from_entity_id": "e1", "into_entity_id": "e2", "reason": "private payload"}]

    async def get_recent_splits(self, tenant_id, limit):
        return []


class _DecisionRepo:
    async def list_for_tenant(self, tenant_id, limit):
        assert tenant_id == "tenant-a"
        return [{"decision_id": "decision-1", "tenant_id": tenant_id, "decision_type": "auto_merge", "entity_id": "e2", "source_connectors": ["shopify"], "email": "person@example.com", "raw_payload": {"access_token": "secret"}}]


class _Jobs:
    async def list_jobs(self, tenant_id, *, job_type, limit):
        assert tenant_id == "tenant-a"
        return [{"id": "job-1", "tenant_id": tenant_id, "job_type": job_type, "status": "succeeded", "payload": {"restatement": {"projection_status": {"profile_360": "succeeded"}, "projection_evidence": {"account_360": {"status": "recomposed", "person_entity_id": "canonical-person", "email": "private@example.com", "person_relationship_count": 2}}, "graph_version_before": "g1", "graph_version_after": "g2", "email": "private@example.com"}}}]


class _Admin:
    async def activation_status(self, tenant_id):
        assert tenant_id == "tenant-a"
        return {"historical_data_status": "available", "sdk_status": "connected", "computed_at": "2026-09-27T10:00:00+00:00", "resolution_counts": {"total_entities": 2, "email": "person@example.com"}, "conflict_counts": {"open": 1}, "projection_restatement_status": "completed", "projection_restatement_counts": {"succeeded": 1}, "sdk_last_seen_at": "device-private"}


class _ScenarioRepo:
    def __init__(self, rows):
        self.rows = rows

    async def list_for_tenant(self, tenant_id, deployment_id, *, limit):
        assert tenant_id == "tenant-a"
        assert deployment_id == "deploy-a"
        assert limit == 100
        return self.rows


@pytest.mark.asyncio
async def test_capture_is_tenant_scoped_redacted_and_does_not_infer_scenarios(monkeypatch):
    reset_identity_scenario_evidence_memory()
    monkeypatch.setattr(staging_capture, "observed_identity_contract_ids", lambda: ["identity-decision"])
    monkeypatch.setattr(staging_capture.settings, "identity_continuity", SimpleNamespace(
        resolution_enabled=True, auto_merge_enabled=True,
        manual_review_enabled=True, conflict_detection_enabled=True,
        split_enabled=True, manual_split_enabled=True,
        auto_split_candidates_enabled=False, sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=False, multi_sdk_stitching_enabled=True,
        connector_backfill_enabled=True, projection_restatement_enabled=True,
        campaign_restatement_enabled=True, value_restatement_enabled=True,
        explainability_enabled=True, activation_dashboard_enabled=True,
        agent_resolution_enabled=True,
    ))
    result = await staging_capture.capture_staging_identity_state(
        "tenant-a", repo=_Repo(), decision_repo=_DecisionRepo(), jobs_service=_Jobs(), admin_service=_Admin()
    )
    serialized = str(result)
    assert "tenant-a" not in serialized
    assert "person@example.com" not in serialized
    assert "private@example.com" not in serialized
    assert "access_token" not in serialized
    assert "sdk_last_seen_at" not in serialized
    assert result["activation"]["resolution_counts"] == {"total_entities": 2}
    assert result["scenario_results"] == []
    assert result["status"] == "captured"
    assert result["merges"][0]["id"].startswith("event:")
    assert result["merges"][0]["from_entity_id"].startswith("entity:")
    assert result["merges"][0]["into_entity_id"].startswith("entity:")
    assert result["merges"][0]["from_entity_id"] != "e1"
    assert result["restatement_jobs"][0]["projection_results"] == {
        "account_360": {"status": "recomposed", "person_relationship_count": 2}
    }
    assert result["projection_outcomes"][0] == {"projection": "profile_360", "status": "completed"}
    assert all(outcome["status"] == "failed" for outcome in result["projection_outcomes"] if outcome["projection"] not in {"profile_360", "syndicates"})
    assert result["projection_outcomes"][-1] == {
        "projection": "account_360", "status": "failed"
    }
    assert "total_entities" in result["health"]


@pytest.mark.asyncio
async def test_capture_includes_only_explicit_records_from_latest_execution_batch(monkeypatch):
    monkeypatch.setattr(staging_capture, "observed_identity_contract_ids", lambda: ["identity-decision"])
    monkeypatch.setattr(staging_capture.settings, "identity_continuity", SimpleNamespace(**{
        name: True for name in staging_capture.REQUIRED_STAGING_IDENTITY_FLAGS
    }))
    now = datetime.now(timezone.utc)
    scenario_repo = _ScenarioRepo([
        {"execution_id": "run-new", "scenario_id": IDENTITY_CONTINUITY_SCENARIOS[0], "outcome": "failed", "executed_at": now, "started_at": now - timedelta(seconds=5), "evidence_sha256": "a" * 64, "assertions_passed": 2, "assertions_failed": 1},
        {"execution_id": "run-old", "scenario_id": IDENTITY_CONTINUITY_SCENARIOS[1], "outcome": "passed", "executed_at": now - timedelta(minutes=1), "started_at": now - timedelta(minutes=2), "evidence_sha256": "b" * 64, "assertions_passed": 3, "assertions_failed": 0},
    ])
    result = await staging_capture.capture_staging_identity_state(
        "tenant-a", repo=_Repo(), decision_repo=_DecisionRepo(), jobs_service=_Jobs(),
        admin_service=_Admin(), scenario_repo=scenario_repo, deployment_id="deploy-a",
    )
    assert len(result["scenario_results"]) == 1
    assert result["scenario_results"][0]["id"] == IDENTITY_CONTINUITY_SCENARIOS[0]
    assert result["scenario_results"][0]["status"] == "failed"
    assert result["scenario_results"][0]["executed_at"] == now.isoformat()
    assert result["scenario_results"][0]["evidence_sha256"] == "a" * 64
    assert result["scenario_results"][0]["execution_ref"].startswith("execution:")
    assert "run-new" not in str(result)
    assert "run-old" not in str(result)


def _scenario_request(**overrides):
    values = {
        "execution_id": str(uuid.uuid4()),
        "scenario_id": IDENTITY_CONTINUITY_SCENARIOS[0],
        "outcome": "passed",
        "evidence_sha256": hashlib.sha256(b"actual-run-output").hexdigest(),
        "assertions_passed": 2,
        "assertions_failed": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    values.update(overrides)
    return ScenarioExecutionRequest.model_validate(values)


def test_scenario_execution_contract_requires_real_explicit_terminal_result():
    _scenario_request()
    with pytest.raises(ValidationError):
        _scenario_request(outcome="passed", assertions_failed=1)
    with pytest.raises(ValidationError):
        _scenario_request(outcome="failed", assertions_failed=0)
    with pytest.raises(ValidationError):
        _scenario_request(scenario_id="fixture_that_was_not_run")
    with pytest.raises(ValidationError):
        _scenario_request(status="passed")
    with pytest.raises(ValidationError):
        _scenario_request(started_at="2026-09-27T10:00:00")


@pytest.mark.asyncio
async def test_durable_scenario_repository_is_idempotent_immutable_and_tenant_deployment_scoped(monkeypatch):
    reset_identity_scenario_evidence_memory()
    async def no_pool():
        return None
    monkeypatch.setattr("identity.identity.scenario_evidence.get_pool", no_pool)
    repository = IdentityScenarioEvidenceRepository()
    request = _scenario_request()
    fields = dict(
        tenant_id="tenant-a", deployment_id="deploy-a", execution_id=request.execution_id,
        scenario_id=request.scenario_id, outcome=request.outcome,
        evidence_sha256=request.evidence_sha256, assertions_passed=request.assertions_passed,
        assertions_failed=request.assertions_failed, started_at=request.started_at,
        actor_ref="actor-hash-a",
    )
    first = await repository.record(**fields)
    replay = await repository.record(**fields)
    assert first == replay
    with pytest.raises(ValueError, match="immutable"):
        await repository.record(**{**fields, "outcome": "failed", "assertions_failed": 1})
    assert len(await repository.list_for_tenant("tenant-a", "deploy-a")) == 1
    assert await repository.list_for_tenant("tenant-b", "deploy-a") == []
    assert await repository.list_for_tenant("tenant-a", "deploy-b") == []


@pytest.mark.asyncio
async def test_staging_scenario_repository_fails_closed_without_durable_database(monkeypatch):
    async def no_pool():
        return None
    monkeypatch.setattr("identity.identity.scenario_evidence.get_pool", no_pool)
    monkeypatch.setattr(
        "identity.identity.scenario_evidence.settings.env",
        SimpleNamespace(value="staging"), raising=False,
    )
    request = _scenario_request()
    with pytest.raises(RuntimeError, match="durable database is required"):
        await IdentityScenarioEvidenceRepository().record(
            tenant_id="tenant-a", deployment_id="deploy-a",
            execution_id=request.execution_id, scenario_id=request.scenario_id,
            outcome=request.outcome, evidence_sha256=request.evidence_sha256,
            assertions_passed=request.assertions_passed,
            assertions_failed=request.assertions_failed,
            started_at=request.started_at, actor_ref="actor-hash",
        )


@pytest.mark.asyncio
async def test_tenant_erasure_deletes_only_that_tenants_scenario_evidence(monkeypatch):
    reset_identity_scenario_evidence_memory()
    async def no_pool():
        return None
    monkeypatch.setattr("identity.identity.scenario_evidence.get_pool", no_pool)
    repository = IdentityScenarioEvidenceRepository()
    for tenant_id in ("tenant-a", "tenant-b"):
        request = _scenario_request()
        await repository.record(
            tenant_id=tenant_id, deployment_id="deploy-a",
            execution_id=request.execution_id, scenario_id=request.scenario_id,
            outcome=request.outcome, evidence_sha256=request.evidence_sha256,
            assertions_passed=request.assertions_passed,
            assertions_failed=request.assertions_failed,
            started_at=request.started_at, actor_ref=f"actor-{tenant_id}",
        )

    assert await repository.delete_for_tenant("tenant-a") == 1
    assert await repository.list_for_tenant("tenant-a", "deploy-a") == []
    assert len(await repository.list_for_tenant("tenant-b", "deploy-a")) == 1


@pytest.mark.asyncio
async def test_scenario_record_endpoint_requires_staging_admin_deployment_and_stores_explicit_result(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "env", SimpleNamespace(value="staging"), raising=False)
    monkeypatch.setenv("AETHER_DEPLOYMENT_ID", "deploy-a")
    rows = []

    class _Repository:
        async def record(self, **kwargs):
            rows.append(kwargs)
            return {**kwargs, "executed_at": datetime.now(timezone.utc)}

    monkeypatch.setattr(staging_capture_routes, "IdentityScenarioEvidenceRepository", _Repository)
    body = _scenario_request()
    with pytest.raises(HTTPException) as missing_auth:
        await staging_capture_routes.record_staging_identity_scenario(body, _Request())
    assert missing_auth.value.status_code == 401
    with pytest.raises(HTTPException) as forbidden:
        await staging_capture_routes.record_staging_identity_scenario(body, _Request(_Tenant({"read"})))
    assert forbidden.value.status_code == 403

    monkeypatch.delenv("AETHER_DEPLOYMENT_ID")
    with pytest.raises(HTTPException) as no_deployment:
        await staging_capture_routes.record_staging_identity_scenario(body, _Request(_Tenant({"admin"})))
    assert no_deployment.value.status_code == 503
    monkeypatch.setenv("AETHER_DEPLOYMENT_ID", "deploy-a")

    tenant = _Tenant({"admin"})
    tenant.entity_id = "raw-admin-identifier"
    response = await staging_capture_routes.record_staging_identity_scenario(body, _Request(tenant))
    assert response["data"]["outcome"] == "passed"
    assert response["data"]["scenario_id"] == body.scenario_id
    assert rows[0]["tenant_id"] == "tenant-a"
    assert rows[0]["deployment_id"] == "deploy-a"
    assert rows[0]["actor_ref"] != "raw-admin-identifier"
    assert "raw-admin-identifier" not in str(response)


class _Tenant:
    tenant_id = "tenant-a"

    def __init__(self, permissions):
        self.permissions = permissions

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise HTTPException(status_code=403, detail="forbidden")


class _Request:
    def __init__(self, tenant=None):
        self.state = SimpleNamespace(tenant=tenant) if tenant else SimpleNamespace()


@pytest.mark.asyncio
async def test_capture_endpoint_is_staging_admin_only_and_requires_deployment(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "env", SimpleNamespace(value="production"), raising=False)
    with pytest.raises(HTTPException) as not_staging:
        await staging_capture_routes.staging_identity_proof_capture(_Request(_Tenant({"admin"})))
    assert not_staging.value.status_code == 404

    monkeypatch.setattr(settings_module.settings, "env", SimpleNamespace(value="staging"), raising=False)
    with pytest.raises(HTTPException) as unauthenticated:
        await staging_capture_routes.staging_identity_proof_capture(_Request())
    assert unauthenticated.value.status_code == 401
    with pytest.raises(HTTPException) as unauthorized:
        await staging_capture_routes.staging_identity_proof_capture(_Request(_Tenant({"read"})))
    assert unauthorized.value.status_code == 403

    monkeypatch.delenv("AETHER_DEPLOYMENT_ID", raising=False)
    with pytest.raises(HTTPException) as no_deployment:
        await staging_capture_routes.staging_identity_proof_capture(_Request(_Tenant({"admin"})))
    assert no_deployment.value.status_code == 503
