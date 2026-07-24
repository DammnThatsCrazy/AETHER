"""Kyber operator ops surface for Agent Access Intelligence (PR 4).

Two properties carry this file.

**The gate is real.** Every route on ``capability_kyber_ops_router`` is exercised over
HTTP with a non-operator tenant — including one holding the legacy ``admin`` permission —
and must answer 403. The route list is read off the router itself, so a route added later
without a gate is a failing test rather than an unguarded cross-tenant read.

**A partial sum is never a total.** When one tenant's bounded read truncates, the
cross-tenant totals must become ``null`` with the absent input named, not the sum of the
tenants that happened to answer. ``_zero_numbers`` (copied from ``test_capability_risk``)
walks the whole response and fails on any zero-valued number anywhere, so a future refactor
cannot reintroduce the lie through a new field: an operator reading "0 unauthorized" when
the truth is "we could not read two of the four tenants" closes the investigation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from config.settings import get_settings
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import AetherError, BadRequestError

import services.agent_access_intelligence.authority as authority_module
import services.agent_access_intelligence.risk_service as risk_service
from services.agent_access_intelligence.authority import capability_authority_service
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.identity import IDENTITY_FIELDS, artifact_digest_for
from services.agent_access_intelligence.kyber_ops_routes import (
    authority_posture,
    capability_kyber_ops_router,
    drift_posture,
    read_authority_posture,
    read_drift_posture,
    read_kyber_blast_radius,
)
from services.security.route_registry import classify

OPERATOR_PERM = get_settings().security_governance.kyber_operator_permission

# Every route the router mounts, with the query string needed to reach its handler.
# `test_every_router_route_is_covered_here` keeps this in step with the router.
ROUTE_QUERIES: dict[str, str] = {
    "/v1/kyber/capability-ops/authority": "",
    "/v1/kyber/capability-ops/drift": "",
    "/v1/kyber/capability-ops/blast-radius": "?tenant_id=t1&agent_id=agentA",
}


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _request(tenant_id: str = "op-tenant", permissions: Optional[list[str]] = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else [OPERATOR_PERM],
    )
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


def _client(permissions: list[str], tenant_id: str = "some-tenant") -> TestClient:
    """A real ASGI app carrying only this router, so the operator gate is exercised as a
    route dependency over HTTP rather than by calling the gate function in isolation."""
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _aether(_request, exc: AetherError):  # noqa: ANN202
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(capability_kyber_ops_router)

    @app.middleware("http")
    async def _inject_tenant(request, call_next):  # noqa: ANN202
        request.state.tenant = TenantContext(
            tenant_id=tenant_id, user_id="u1", permissions=permissions
        )
        return await call_next(request)

    return TestClient(app)


async def _seed_capability(
    tenant_id: str,
    *,
    source_event_id: str = "e1",
    agent_id: Optional[str] = "agentA",
    tool_name: str = "search",
    server_name: str = "srvX",
    provider: str = "acme",
) -> str:
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": agent_id,
        "tool_name": tool_name,
        "server_name": server_name,
        "provider": provider,
        "protocol_version": "2025-06-18",
        "risk_level": "high",
    })
    return result["capability_id"]


async def _grant(tenant_id: str, capability_id: str, *, agent_id: str = "agentA") -> dict:
    return await capability_authority_service.grant(
        tenant_id=tenant_id,
        granted_by_entity_id="u1",
        agent_id=agent_id,
        capability_id=capability_id,
    )


class StubDeclarations:
    """Per-tenant declared digests, so drift is driven by this test rather than by the
    declarations lane's write path (same approach as ``test_capability_risk``)."""

    def __init__(self, by_tenant: dict[str, dict[str, str]], *, truncated: bool = False):
        self.by_tenant = by_tenant
        self.truncated = truncated

    async def digest_map(self, tenant_id: str, *, limit: int = 1000):
        declared = self.by_tenant.get(tenant_id, {})
        return (
            {k: {"digest": v, "fields": list(IDENTITY_FIELDS)} for k, v in declared.items()},
            self.truncated,
        )


def _zero_numbers(value: Any, path: str = "$") -> list[str]:
    """Every path in ``value`` holding a numeric zero. ``bool`` is excluded on purpose —
    ``False`` is an ``int`` in Python and ``totals_known: false`` is the honest answer,
    not a count. (Copied from ``test_capability_risk.py``.)"""
    hits: list[str] = []
    if isinstance(value, bool):
        return hits
    if isinstance(value, (int, float)):
        if value == 0:
            hits.append(path)
        return hits
    if isinstance(value, dict):
        for key, item in value.items():
            hits.extend(_zero_numbers(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_zero_numbers(item, f"{path}[{index}]"))
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# A. Operator gate — real, and on every route
# ══════════════════════════════════════════════════════════════════════════════

def test_every_router_route_is_covered_here():
    """A route added without a gate assertion fails here rather than shipping ungated."""
    assert {route.path for route in capability_kyber_ops_router.routes} == set(ROUTE_QUERIES)


@pytest.mark.parametrize("path", sorted(ROUTE_QUERIES))
def test_non_operator_is_refused_on_every_route(path):
    client = _client(["read", "write"])
    assert client.get(f"{path}{ROUTE_QUERIES[path]}").status_code == 403


@pytest.mark.parametrize("path", sorted(ROUTE_QUERIES))
def test_role_admin_tenant_is_still_not_an_operator(path):
    """`is_kyber_operator` reads the RAW permission list precisely so a role-admin Aether
    tenant cannot reach a cross-tenant surface."""
    client = _client(["admin", "read", "write"])
    assert client.get(f"{path}{ROUTE_QUERIES[path]}").status_code == 403


@pytest.mark.parametrize("path", sorted(ROUTE_QUERIES))
def test_operator_is_admitted_on_every_route(path):
    client = _client([OPERATOR_PERM])
    response = client.get(f"{path}{ROUTE_QUERIES[path]}")
    assert response.status_code == 200, response.text
    assert "data" in response.json()


def test_kyber_paths_are_auto_classified_without_a_registry_entry():
    """`/v1/kyber` is already a known prefix and any path containing `/kyber` classifies as
    operator + audit + high — so this prefix needs no `config/route_registry.yaml` entry."""
    for path in ROUTE_QUERIES:
        policy = classify(path)
        assert policy is not None, f"{path} is unclassified"
        assert policy.kyber_operator_required is True
        assert policy.audit_required is True
        assert policy.risk_class == "high"


# ══════════════════════════════════════════════════════════════════════════════
# B. Cross-tenant aggregation is a fan-out of explicitly scoped reads
# ══════════════════════════════════════════════════════════════════════════════

async def test_authority_aggregates_tenants_without_bleeding_between_them(monkeypatch):
    cap_t1 = await _seed_capability("t1", source_event_id="a")
    cap_t2 = await _seed_capability("t2", source_event_id="b")
    await _grant("t1", cap_t1)
    revoked = await _grant("t2", cap_t2)
    await capability_authority_service.revoke(
        tenant_id="t2", authorization_id=revoked["authorization_id"], revoked_by_entity_id="u1"
    )

    seen_tenant_ids: list[Optional[str]] = []
    original = capability_authority_service.count_by_state

    async def _spy(*, tenant_id: str, agent_id: Optional[str] = None):
        seen_tenant_ids.append(tenant_id)
        return await original(tenant_id=tenant_id, agent_id=agent_id)

    monkeypatch.setattr(capability_authority_service, "count_by_state", _spy)

    data = await authority_posture()

    # Every cross-tenant read named exactly one tenant.
    assert sorted(seen_tenant_ids) == ["t1", "t2"]
    assert all(tid for tid in seen_tenant_ids), "an unscoped cross-tenant query was issued"

    assert data["totals_known"] is True
    assert data["missing_inputs"] == []
    assert data["counts_by_state"]["active"] == 1
    assert data["counts_by_state"]["revoked"] == 1
    # A state nobody is in is a computed zero here — every window was complete.
    assert data["counts_by_state"]["expired"] == 0

    by_tenant = {row["tenant_id"]: row for row in data["tenants"]}
    assert by_tenant["t1"]["counts_by_state"] == {
        "active": 1, "pending": 0, "expired": 0, "revoked": 0
    }
    assert by_tenant["t2"]["counts_by_state"] == {
        "active": 0, "pending": 0, "expired": 0, "revoked": 1
    }
    assert data["tenant_discovery"]["tenants_examined"] == 2
    assert data["tenant_discovery"]["complete"] is True


async def test_authority_route_returns_the_aggregate():
    cap = await _seed_capability("t1")
    await _grant("t1", cap)
    response = await read_authority_posture(_request())
    assert response["data"]["counts_by_state"]["active"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# C. THE RULE — a truncated per-tenant read makes the total null, never a partial sum
# ══════════════════════════════════════════════════════════════════════════════

async def test_truncated_tenant_read_nulls_the_authority_totals(monkeypatch):
    """The load-bearing test. One tenant's authorization window truncates, so the
    cross-tenant totals could not be computed — they must be ``null``, not the number of
    rows that fitted inside the window."""
    cap = await _seed_capability("t1")
    await _grant("t1", cap)
    await _grant("t1", cap, agent_id="agentB")
    # The bounded window `count_by_state` scans is now exactly full.
    monkeypatch.setattr(authority_module, "_STATE_FILTER_SCAN", 2)

    data = await authority_posture()

    assert data["totals_known"] is False
    assert "capability_authorizations:scan_truncated:tenant_id=t1" in data["missing_inputs"]

    # Every cross-tenant total is null — not 2, which is what the readable window held.
    assert set(data["counts_by_state"]) == {"active", "pending", "expired", "revoked"}
    for state, value in data["counts_by_state"].items():
        assert value is None, f"counts_by_state.{state} must be null when unknowable"

    # The tenant row that could not be read is null too, and says why.
    row = data["tenants"][0]
    assert row["known"] is False
    assert row["missing_inputs"]
    assert all(v is None for v in row["counts_by_state"].values())

    # And nowhere else in the response is there a zero pretending to be a count.
    assert _zero_numbers(data) == []
    assert "UNKNOWN" in data["summary"]
    assert "not zero" in data["summary"]


async def test_readable_tenants_are_not_summed_into_a_total(monkeypatch):
    """Two tenants, one readable and one truncated: the total is still null. Summing only
    the tenant that answered would report a confident number that is missing a tenant."""
    cap_t1 = await _seed_capability("t1", source_event_id="a")
    cap_t2 = await _seed_capability("t2", source_event_id="b")
    await _grant("t1", cap_t1)
    await _grant("t2", cap_t2)
    await _grant("t2", cap_t2, agent_id="agentB")

    original = capability_authority_service.count_by_state

    async def _truncate_t2(*, tenant_id: str, agent_id: Optional[str] = None):
        snapshot = await original(tenant_id=tenant_id, agent_id=agent_id)
        if tenant_id == "t2":
            return {**snapshot, "truncated": True}
        return snapshot

    monkeypatch.setattr(capability_authority_service, "count_by_state", _truncate_t2)

    data = await authority_posture()

    assert data["totals_known"] is False
    assert data["counts_by_state"]["active"] is None, "a partial sum was presented as a total"
    by_tenant = {row["tenant_id"]: row for row in data["tenants"]}
    # The readable tenant keeps its numbers — as evidence, clearly attributed.
    assert by_tenant["t1"]["known"] is True
    assert by_tenant["t1"]["counts_by_state"]["active"] == 1
    assert by_tenant["t2"]["known"] is False


async def test_incomplete_tenant_discovery_nulls_the_totals(monkeypatch):
    """If the tenant list itself is partial, every tenant we did read is still a subset."""
    cap = await _seed_capability("t1")
    await _grant("t1", cap)
    original = capability_catalog_service.catalog_health

    async def _sampled():
        return {**await original(), "sampled": True}

    monkeypatch.setattr(capability_catalog_service, "catalog_health", _sampled)

    data = await authority_posture()
    assert data["totals_known"] is False
    assert "capability_catalog:tenant_discovery_truncated" in data["missing_inputs"]
    assert all(v is None for v in data["counts_by_state"].values())
    assert data["tenant_discovery"]["complete"] is False


# ══════════════════════════════════════════════════════════════════════════════
# D. Drift
# ══════════════════════════════════════════════════════════════════════════════

async def test_drift_aggregates_findings_across_tenants(monkeypatch):
    cap_t1 = await _seed_capability("t1", source_event_id="a")
    await _seed_capability("t2", source_event_id="b")
    monkeypatch.setattr(
        risk_service,
        "capability_declaration_service",
        StubDeclarations({"t1": {cap_t1: "sha256:stale-declared-digest"}}),
    )

    data = await drift_posture()

    assert data["totals_known"] is True
    assert data["counts"]["drifted"] == 1
    assert data["counts"]["capabilities_examined"] == 2
    assert data["findings_scope"] == "all_matching_findings"
    assert [f["tenant_id"] for f in data["findings"]] == ["t1"]
    assert data["findings"][0]["capability_id"] == cap_t1

    by_tenant = {row["tenant_id"]: row for row in data["tenants"]}
    assert by_tenant["t1"]["counts"]["drifted"] == 1
    assert by_tenant["t2"]["counts"]["drifted"] == 0


async def test_declared_capability_that_still_matches_is_not_drift(monkeypatch):
    cap = await _seed_capability("t1")
    record = await capability_catalog_service.get_capability("t1", cap)
    monkeypatch.setattr(
        risk_service,
        "capability_declaration_service",
        StubDeclarations({"t1": {cap: artifact_digest_for(record, list(IDENTITY_FIELDS))}}),
    )
    data = await drift_posture()
    assert data["counts"]["drifted"] == 0
    assert data["counts"]["declared"] == 1
    assert data["findings"] == []


async def test_truncated_catalog_read_nulls_the_drift_totals(monkeypatch):
    await _seed_capability("t1", source_event_id="a", tool_name="search")
    await _seed_capability("t1", source_event_id="b", tool_name="write")
    monkeypatch.setattr(risk_service, "_CATALOG_SCAN_LIMIT", 1)
    monkeypatch.setattr(risk_service, "capability_declaration_service", StubDeclarations({}))

    data = await drift_posture()

    assert data["totals_known"] is False
    assert "capability_catalog:scan_truncated:tenant_id=t1" in data["missing_inputs"]
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null when the scan truncated"
    assert data["findings_scope"] == "evidence_only_incomplete_scan"
    assert data["tenants"][0]["known"] is False
    assert _zero_numbers(data) == []


async def test_truncated_declarations_null_the_drift_totals(monkeypatch):
    """A declaration outside the window makes its capability look undeclared, and
    undeclared is deliberately not a finding — so drift would vanish into a clean report."""
    await _seed_capability("t1")
    monkeypatch.setattr(
        risk_service, "capability_declaration_service", StubDeclarations({}, truncated=True)
    )

    data = await drift_posture()

    assert data["totals_known"] is False
    assert "capability_declarations:scan_truncated:tenant_id=t1" in data["missing_inputs"]
    assert all(v is None for v in data["counts"].values())
    assert _zero_numbers(data) == []


async def test_drift_route_returns_the_aggregate(monkeypatch):
    cap = await _seed_capability("t1")
    monkeypatch.setattr(
        risk_service,
        "capability_declaration_service",
        StubDeclarations({"t1": {cap: "sha256:stale"}}),
    )
    response = await read_drift_posture(_request(), findings_per_tenant=50)
    assert response["data"]["counts"]["drifted"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# E. Blast radius — bounded to one explicitly named tenant
# ══════════════════════════════════════════════════════════════════════════════

async def test_blast_radius_requires_a_tenant_id():
    with pytest.raises(BadRequestError):
        await read_kyber_blast_radius(
            _request(), tenant_id="   ", agent_id="agentA", capability_id=None
        )


async def test_blast_radius_is_scoped_to_the_named_tenant():
    await _seed_capability("t1")
    # The same agent id, reviewed under a tenant that never observed it.
    response = await read_kyber_blast_radius(
        _request(), tenant_id="t2", agent_id="agentA", capability_id=None
    )
    data = response["data"]
    assert data["tenant_id"] == "t2"
    assert data["exposure_known"] is False
    assert any("agentA" in entry for entry in data["missing_inputs"])
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null, never 0"
    assert _zero_numbers(data) == []


async def test_blast_radius_reports_a_known_exposure_for_an_observed_agent():
    cap = await _seed_capability("t1")
    response = await read_kyber_blast_radius(
        _request(), tenant_id="t1", agent_id="agentA", capability_id=None
    )
    data = response["data"]
    assert data["tenant_id"] == "t1"
    assert data["exposure_known"] is True
    assert data["counts"]["capabilities_exposed"] == 1
    # `authorized` is tri-state; with a computable split it is a real boolean.
    assert data["capabilities"][0]["capability_id"] == cap
    assert data["capabilities"][0]["authorized"] is False


async def test_blast_radius_authorized_is_unknown_when_the_split_cannot_be_computed(
    monkeypatch,
):
    cap = await _seed_capability("t1")
    await _grant("t1", cap)
    monkeypatch.setattr(risk_service, "_AUTHORIZATION_SCAN_LIMIT", 1)

    response = await read_kyber_blast_radius(
        _request(), tenant_id="t1", agent_id="agentA", capability_id=None
    )
    data = response["data"]
    assert data["exposure_known"] is False
    assert "capability_authorizations:scan_truncated" in data["missing_inputs"]
    # null, not False — "we could not read the authorizations" is not "denied".
    assert data["capabilities"][0]["authorized"] is None
    assert all(v is None for v in data["counts"].values())
