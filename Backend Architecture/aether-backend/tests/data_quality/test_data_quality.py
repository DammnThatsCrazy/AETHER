"""Tests for Data Quality / Drift Detection / Intelligence Quality."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.data_quality import routes as dq
from services.data_quality.models import QUALITY_DIMENSIONS
from services.data_quality.service import (
    drift_service,
    intelligence_quality_service,
)
from services.security import audit_ledger as audit_mod
from services.security.repositories import SecurityAuditEventRepository

pytestmark = pytest.mark.asyncio

OP_PERMS = ["kyber:operator", "admin"]


class Tenant:
    def __init__(self, tenant_id="tenant-a", permissions=None, user_id="user-1"):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.permissions = list(permissions if permissions is not None else ["read", "write", "admin"])

    def has_permission(self, permission):
        return permission in self.permissions

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise PermissionError(f"missing permission {permission}")


def req(tenant_id="tenant-a", permissions=None):
    return SimpleNamespace(
        state=SimpleNamespace(tenant=Tenant(tenant_id, permissions)),
        client=None,
        headers={},
    )


def unwrap(resp):
    return resp["data"]


@pytest.fixture(autouse=True)
def clean():
    reset_in_memory_stores()
    audit_mod._TENANT_TAIL.clear()
    audit_mod._TENANT_SEQ.clear()


# ── Intelligence quality scoring ─────────────────────────────────────────────

async def test_intelligence_quality_score_is_normalized_and_complete():
    score = await intelligence_quality_service.compute_score("tenant-a")
    for field in QUALITY_DIMENSIONS:
        assert 0.0 <= score[field] <= 1.0
    assert 0.0 <= score["overall_intelligence_quality_score"] <= 1.0
    assert score["status"] in ("healthy", "watch", "degraded", "critical")
    assert score["tenant_id"] == "tenant-a"


async def test_scores_are_deterministic_per_tenant():
    a1 = await intelligence_quality_service.compute_score("tenant-a")
    a2 = await intelligence_quality_service.compute_score("tenant-a")
    b = await intelligence_quality_service.compute_score("tenant-b")
    assert a1["overall_intelligence_quality_score"] == a2["overall_intelligence_quality_score"]
    # different tenants get distinct (but stable) jittered scores
    assert a1["overall_intelligence_quality_score"] != b["overall_intelligence_quality_score"]


async def test_dimension_reports_expose_tracked_metrics():
    events = intelligence_quality_service.dimension_report("events", "tenant-a")
    assert "event_volume" in events and "quality_score" in events and "status" in events
    schema = intelligence_quality_service.dimension_report("schema", "tenant-a")
    assert "change_type_counts" in schema
    identity = intelligence_quality_service.dimension_report("identity", "tenant-a")
    assert "merge_rate" in identity
    graph = intelligence_quality_service.dimension_report("graph", "tenant-a")
    assert "orphaned_vertices" in graph


# ── Tenant-facing routes (isolation + auth) ──────────────────────────────────

async def test_tenant_overview_route():
    data = unwrap(await dq.data_quality_overview(req("tenant-a")))
    assert "score" in data and "dimensions" in data
    assert data["score"]["tenant_id"] == "tenant-a"
    assert len(data["dimensions"]) == len(QUALITY_DIMENSIONS)
    # seeded drift is platform-wide (tenant_id=None) so the tenant sees none of it
    assert data["open_drift_event_count"] == 0


async def test_tenant_route_requires_read_permission():
    with pytest.raises(PermissionError):
        await dq.data_quality_events(req("tenant-a", permissions=[]))


async def test_tenant_routes_do_not_leak_other_tenants():
    payload = unwrap(await dq.data_quality_overview(req("tenant-a")))
    assert "tenant-b" not in str(payload)


# ── Kyber operator gating ─────────────────────────────────────────────────────

async def test_kyber_route_denies_plain_tenant_admin():
    from shared.common.common import ForbiddenError
    # A normal Aether tenant — even with "admin" — is not a Kyber operator.
    with pytest.raises(ForbiddenError):
        await dq.intelligence_quality_overview(req("tenant-a", permissions=["admin", "read"]))


async def test_kyber_route_allows_operator():
    data = unwrap(await dq.intelligence_quality_overview(req("olympus", permissions=OP_PERMS)))
    assert data["score"]["scope"] == "platform"


async def test_kyber_tenants_view_is_aggregate_only():
    data = unwrap(await dq.intelligence_quality_tenants(req("olympus", permissions=OP_PERMS), tenant_ids=None))
    assert data["items"], "expected aggregate per-tenant scores"
    for row in data["items"]:
        # aggregate-only: scalar score + status, never raw per-dimension payloads
        assert set(row.keys()) == {"tenant_id", "overall_intelligence_quality_score", "status", "calculated_at"}


# ── Drift events ─────────────────────────────────────────────────────────────

async def test_drift_events_seeded_and_listed():
    items = await drift_service.list()
    assert len(items) >= 3
    types = {d["drift_type"] for d in items}
    assert "schema_drift" in types


async def test_drift_acknowledge_and_resolve_lifecycle():
    operator = req("olympus", permissions=OP_PERMS)
    acked = unwrap(await dq.intelligence_quality_acknowledge("drift_seed_reco_quality", operator))
    assert acked["status"] == "acknowledged" and acked["acknowledged_at"]
    resolved = unwrap(await dq.intelligence_quality_resolve("drift_seed_reco_quality", operator, dq.DriftResolve(resolution_note="tuned weights")))
    assert resolved["status"] == "resolved" and resolved["resolved_at"]


async def test_resolve_unknown_drift_raises():
    from shared.common.common import NotFoundError
    with pytest.raises(NotFoundError):
        await dq.intelligence_quality_resolve("nope", req("olympus", permissions=OP_PERMS), None)


async def test_drift_mutation_requires_operator_admin():
    # read-only operator (no admin) cannot acknowledge/resolve
    with pytest.raises(PermissionError):
        await dq.intelligence_quality_acknowledge("drift_seed_reco_quality", req("olympus", permissions=["kyber:operator"]))


# ── Contamination → Security/Governance escalation ───────────────────────────

async def test_critical_contamination_escalates_to_audit_ledger():
    repo = SecurityAuditEventRepository()
    before = len(await repo.list_all(limit=1000))
    drift = await drift_service.detect_contamination(
        tenant_id="tenant-a",
        severity="critical",
        reason="cross-tenant identifiers detected on ingested events",
        supporting_metrics={"cross_tenant_identifiers": 7},
    )
    assert drift["escalated_audit_event_id"]
    after = await repo.list_all(limit=1000)
    assert len(after) == before + 1
    assert any(e.get("event_type") == "data_quality_contamination_detected" for e in after)


async def test_low_severity_contamination_does_not_escalate():
    repo = SecurityAuditEventRepository()
    before = len(await repo.list_all(limit=1000))
    drift = await drift_service.detect_contamination(
        tenant_id="tenant-a",
        severity="low",
        reason="single record missing tenant_id (auto-corrected)",
        supporting_metrics={"records_missing_tenant_id": 1},
    )
    assert drift["escalated_audit_event_id"] is None
    after = len(await repo.list_all(limit=1000))
    assert after == before


async def test_contamination_audit_metadata_has_no_secrets():
    import json
    await drift_service.detect_contamination(
        tenant_id="tenant-a",
        severity="critical",
        reason="leak",
        supporting_metrics={"api_key": "sk_live_should_be_stripped", "cross_tenant_identifiers": 2},
    )
    repo = SecurityAuditEventRepository()
    events = await repo.list_all(limit=1000)
    blob = json.dumps(events)
    assert "sk_live_should_be_stripped" not in blob
