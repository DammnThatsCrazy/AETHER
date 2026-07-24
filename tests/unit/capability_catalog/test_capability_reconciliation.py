"""Capability reconciliation — observed inventory vs provider-reported state (PR 3).

Handlers are called directly with a fake ``Request`` — the established pattern in this
suite (``test_capability_authority_routes.py``, ``test_capability_risk.py``) — so
permission gates and tenant scoping are exercised without standing up the middleware.

Two tests here are load-bearing:

``test_no_provider_evidence_is_unknown_not_zero``
    With nothing reported by any provider, the report must be UNKNOWN: ``null`` counts,
    an explicit ``missing_inputs``, and a summary that says so. "0 mismatches" reads as
    "everything reconciles", which is a claim about the world that no input supports. The
    test walks the entire response recursively and fails on any zero-valued number
    anywhere in it, so a future refactor cannot reintroduce the lie through a new field.

``test_orphan_is_suppressed_when_there_is_nothing_to_compare_against``
    Observing capabilities nobody registered is this platform's normal output. An orphan
    is only a finding when the provider actually reports evidence for this tenant, and is
    a count otherwise — the same trap ``risk_service``'s ``observed_only`` avoided.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

import services.agent_access_intelligence.reconciliation_routes as reconciliation_routes
import services.agent_access_intelligence.reconciliation_service as reconciliation_service
from repositories.repos import reset_in_memory_stores
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError


class StubProviderEvidence:
    """Stands in for the provider-evidence lane, honouring its published contract:
    ``list(*, tenant_id, provider_id=None, capability_id=None, limit=100, offset=0)``
    returning rows that carry ``provider_id``, ``capability_id``,
    ``external_account_id``, ``agent_id``, ``verification_status``, ``verified_at`` and
    ``evidence_digest``.

    Evidence is driven from here rather than through that lane's write path, so this
    lane's comparison logic is verifiable independently of that module's storage — the
    same reason ``test_capability_risk.py`` stubs ``capability_declaration_service``.
    Rows are held per tenant, so cross-tenant scoping is a property of the stub rather
    than an assumption about the caller."""

    def __init__(self, by_tenant: Optional[dict[str, list[dict]]] = None) -> None:
        self.by_tenant = {k: list(v) for k, v in (by_tenant or {}).items()}
        self.calls: list[dict[str, Any]] = []

    async def list(
        self,
        *,
        tenant_id: str,
        provider_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        self.calls.append({
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "capability_id": capability_id,
            "limit": limit,
            "offset": offset,
        })
        rows = self.by_tenant.get(tenant_id, [])
        if provider_id:
            rows = [r for r in rows if r.get("provider_id") == provider_id]
        if capability_id:
            rows = [r for r in rows if r.get("capability_id") == capability_id]
        return [dict(r) for r in rows[offset : offset + limit]]


def _evidence(
    *,
    provider_id: str = "acme",
    capability_id: Optional[str] = None,
    external_account_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    verification_status: str = "verified",
    verified_at: str = "2026-07-25T00:00:00Z",
    evidence_digest: str = "sha256:stub",
) -> dict:
    return {
        "provider_id": provider_id,
        "capability_id": capability_id,
        "external_account_id": external_account_id,
        "agent_id": agent_id,
        "verification_status": verification_status,
        "verified_at": verified_at,
        "evidence_digest": evidence_digest,
    }


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture(autouse=True)
def _no_evidence(monkeypatch):
    """No provider reports anything unless a test says otherwise."""
    stub = StubProviderEvidence()
    monkeypatch.setattr(reconciliation_service, "provider_evidence_service", stub)
    return stub


def _use(monkeypatch, by_tenant: dict[str, list[dict]]) -> StubProviderEvidence:
    stub = StubProviderEvidence(by_tenant)
    monkeypatch.setattr(reconciliation_service, "provider_evidence_service", stub)
    return stub


async def _seed(
    tenant_id: str = "t1",
    *,
    source_event_id: str = "e1",
    agent_id: Optional[str] = "agentA",
    tool_name: Optional[str] = "search",
    server_name: Optional[str] = "srvX",
    server_url: Optional[str] = None,
    provider: str = "acme",
    occurred_at: str = "2026-07-24T00:00:00Z",
) -> str:
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": occurred_at,
        "agent_id": agent_id,
        "tool_name": tool_name,
        "server_name": server_name,
        "server_url": server_url,
        "provider": provider,
        "risk_level": "high",
    })
    return result["capability_id"]


def _zero_numbers(value: Any, path: str = "$") -> list[str]:
    """Every path in ``value`` holding a numeric zero. ``bool`` is excluded on purpose —
    ``False`` is an ``int`` in Python and ``reconciliation_known: false`` is the honest
    answer, not a count."""
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


def _kinds(items: list[dict]) -> list[str]:
    return sorted(i["kind"] for i in items)


# ══════════════════════════════════════════════════════════════════════════════
# UNKNOWN IS NEVER ZERO
# ══════════════════════════════════════════════════════════════════════════════

async def test_no_provider_evidence_is_unknown_not_zero():
    # A populated catalog, so "empty store" is not what makes this pass.
    await _seed(source_event_id="e1", tool_name="search")
    await _seed(source_event_id="e2", tool_name="write")

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    assert data["reconciliation_known"] is False
    assert data["missing_inputs"], "an absent input must be named, not silently dropped"
    assert any("provider_evidence" in entry for entry in data["missing_inputs"])

    # Every count is null. Not 0 — 0 would say the two sides agree.
    assert set(data["counts"]) == {
        "missing",
        "orphan",
        "mismatch",
        "total",
        "observed_without_evidence",
        "orphan_not_comparable",
    }
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null when it could not be computed"

    # And nowhere else in the response either.
    assert _zero_numbers(data) == []

    assert data["coverage"]["complete"] is False
    assert "UNKNOWN" in data["summary"]
    assert "not zero" in data["summary"]


async def test_cross_tenant_evidence_is_unknown_identically_to_absent(monkeypatch):
    stub = _use(monkeypatch, {"t1": [_evidence(capability_id="cap-x")]})
    await _seed("t1")

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t2"), provider_id=None, kind=None, limit=100
    ))["data"]

    # t2 sees the same answer it would see if t1's evidence did not exist at all.
    assert data["reconciliation_known"] is False
    assert any("provider_evidence:none_for" in e for e in data["missing_inputs"])
    assert _zero_numbers(data) == []
    # Tenant came from request.state.tenant, never from a parameter.
    assert [c["tenant_id"] for c in stub.calls] == ["t2"]


# ══════════════════════════════════════════════════════════════════════════════
# THE THREE FINDING KINDS
# ══════════════════════════════════════════════════════════════════════════════

async def test_missing_orphan_and_mismatch_are_all_produced(monkeypatch):
    cap_a = await _seed(source_event_id="e1", tool_name="search", server_name="srvX")
    cap_b = await _seed(source_event_id="e2", tool_name="write", server_name="srvY")
    # A capability from a provider that reports nothing at all — never a finding.
    cap_c = await _seed(
        source_event_id="e3", tool_name="read", server_name="srvZ", provider="quiet-co"
    )

    _use(monkeypatch, {"t1": [
        # Both sides know cap_a, and disagree about who reaches it.
        _evidence(capability_id=cap_a, agent_id="ghost-agent"),
        # The provider reports a capability we have never observed.
        _evidence(capability_id="cap-never-observed", external_account_id="acct-9"),
    ]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    assert data["reconciliation_known"] is True
    assert data["missing_inputs"] == []
    assert data["counts"]["missing"] == 1
    assert data["counts"]["mismatch"] == 1
    assert data["counts"]["orphan"] == 1
    assert data["counts"]["total"] == 3
    assert _kinds(data["items"]) == ["mismatch", "missing", "orphan"]

    by_kind = {i["kind"]: i for i in data["items"]}
    assert by_kind["missing"]["capability_id"] == "cap-never-observed"
    assert by_kind["missing"]["external_account_id"] == "acct-9"
    assert by_kind["mismatch"]["capability_id"] == cap_a
    assert by_kind["mismatch"]["attribute"] == "agent_attribution"
    assert by_kind["mismatch"]["reported"] == "ghost-agent"
    assert by_kind["mismatch"]["observed"] == ["agentA"]
    # cap_b's provider (acme) does report to us and said nothing about it → comparable.
    assert by_kind["orphan"]["capability_id"] == cap_b

    # cap_c's provider reports nothing, so it is counted, never emitted.
    assert cap_c not in {i["capability_id"] for i in data["items"]}
    assert data["counts"]["observed_without_evidence"] == 2
    assert data["counts"]["orphan_not_comparable"] == 1

    # Severity is reused from RiskLevel; no new enum was introduced.
    assert {i["risk_level"] for i in data["items"]} <= {"low", "medium", "high", "critical"}
    assert by_kind["mismatch"]["risk_level"] == "high"
    assert by_kind["orphan"]["risk_level"] == "low"

    assert data["coverage"]["capabilities_matched"] == 1
    assert data["coverage"]["evidence_examined"] == 2
    assert data["coverage"]["complete"] is True


async def test_stale_provider_verification_is_a_mismatch(monkeypatch):
    cap_id = await _seed(occurred_at="2026-07-24T00:00:00Z", agent_id="agentA")
    _use(monkeypatch, {"t1": [
        _evidence(capability_id=cap_id, agent_id="agentA", verified_at="2026-07-20T00:00:00Z")
    ]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    assert data["counts"]["mismatch"] == 1
    item = data["items"][0]
    assert item["attribute"] == "verification_status"
    assert item["observed"] == "2026-07-24T00:00:00Z"
    assert "predates" in item["summary"]
    # Agent attribution agreed, so only ONE mismatch was raised.
    assert data["counts"]["total"] == 1


async def test_attribution_mismatch_is_not_fabricated_when_we_observed_no_agent(monkeypatch):
    # A provider action with no server → no installation row → no observed agent to
    # disagree with. You cannot diverge from an assertion nobody made.
    cap_id = await _seed(server_name=None, server_url=None, tool_name="transfer")
    _use(monkeypatch, {"t1": [_evidence(capability_id=cap_id, agent_id="ghost-agent")]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    assert data["counts"]["mismatch"] == 0
    assert data["counts"]["total"] == 0
    assert data["coverage"]["capabilities_matched"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# ORPHAN SUPPRESSION
# ══════════════════════════════════════════════════════════════════════════════

async def test_orphan_is_suppressed_when_there_is_nothing_to_compare_against(monkeypatch):
    # Three observed capabilities from a provider that reports nothing, plus one evidence
    # row for a DIFFERENT provider so the report is computable at all.
    for index in range(3):
        await _seed(
            source_event_id=f"e{index}",
            tool_name=f"tool{index}",
            server_name="srvQ",
            provider="quiet-co",
        )
    _use(monkeypatch, {"t1": [_evidence(provider_id="acme", capability_id="cap-elsewhere")]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    # Not one orphan item — every observed capability belongs to a provider that has never
    # reported anything, so "observed but unreported" says nothing.
    assert data["counts"]["orphan"] == 0
    assert [i for i in data["items"] if i["kind"] == "orphan"] == []
    # Reported as a count instead, so the operator can still see the shape of the tenant.
    assert data["counts"]["observed_without_evidence"] == 3
    assert data["counts"]["orphan_not_comparable"] == 3
    assert data["coverage"]["providers_with_evidence"] == ["acme"]
    assert "normal output" in data["summary"]


async def test_orphan_becomes_a_finding_once_that_provider_reports(monkeypatch):
    cap_id = await _seed(provider="quiet-co", server_name="srvQ")
    # Same provider now reports something else — the comparison becomes meaningful.
    _use(monkeypatch, {"t1": [
        _evidence(provider_id="quiet-co", capability_id="cap-elsewhere")
    ]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    orphans = [i for i in data["items"] if i["kind"] == "orphan"]
    assert [i["capability_id"] for i in orphans] == [cap_id]
    assert data["counts"]["orphan_not_comparable"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# BOUNDED READS ARE DISCLOSED
# ══════════════════════════════════════════════════════════════════════════════

async def test_truncated_evidence_window_makes_the_comparison_unknown(monkeypatch):
    await _seed()
    monkeypatch.setattr(reconciliation_service, "_EVIDENCE_SCAN_LIMIT", 1)
    _use(monkeypatch, {"t1": [
        _evidence(capability_id="cap-1"),
        _evidence(capability_id="cap-2"),
    ]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    assert data["reconciliation_known"] is False
    assert "provider_evidence:scan_truncated" in data["missing_inputs"]
    assert all(v is None for v in data["counts"].values())
    assert data["coverage"]["complete"] is False


async def test_truncated_catalog_window_makes_the_comparison_unknown(monkeypatch):
    await _seed(source_event_id="e1", tool_name="search")
    await _seed(source_event_id="e2", tool_name="write")
    monkeypatch.setattr(reconciliation_service, "_CATALOG_SCAN_LIMIT", 1)
    _use(monkeypatch, {"t1": [_evidence(capability_id="cap-1")]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]

    assert data["reconciliation_known"] is False
    assert "capability_catalog:scan_truncated" in data["missing_inputs"]
    assert all(v is None for v in data["counts"].values())


async def test_item_limit_truncation_is_disclosed_and_counts_stay_whole(monkeypatch):
    await _seed(source_event_id="e1", tool_name="search")
    await _seed(source_event_id="e2", tool_name="write")
    _use(monkeypatch, {"t1": [
        _evidence(capability_id="cap-missing-1"),
        _evidence(capability_id="cap-missing-2"),
    ]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=1
    ))["data"]

    assert len(data["items"]) == 1
    assert data["items_truncated"] is True
    assert data["limit"] == 1
    # The page shrank; the report did not.
    assert data["counts"]["total"] == 4
    assert data["counts"]["missing"] == 2
    assert data["counts"]["orphan"] == 2
    assert data["coverage"]["complete"] is False


async def test_kind_filter_pages_items_without_zeroing_the_other_kinds(monkeypatch):
    await _seed(source_event_id="e1", tool_name="search")
    _use(monkeypatch, {"t1": [_evidence(capability_id="cap-missing-1")]})

    data = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind="missing", limit=100
    ))["data"]

    assert _kinds(data["items"]) == ["missing"]
    assert data["filter"]["kind"] == "missing"
    # Counts describe the whole comparison, so the filtered-out orphan is still visible.
    assert data["counts"]["orphan"] == 1
    assert data["counts"]["total"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSIONS + TENANT SCOPING
# ══════════════════════════════════════════════════════════════════════════════

async def test_every_route_requires_read_and_only_read(monkeypatch):
    _use(monkeypatch, {"t1": [_evidence(capability_id="cap-1")]})
    with pytest.raises(ForbiddenError):
        await reconciliation_routes.read_reconciliation_report(
            _request("t1", permissions=[]), provider_id=None, kind=None, limit=100
        )
    with pytest.raises(ForbiddenError):
        await reconciliation_routes.read_pipeline_health(_request("t1", permissions=[]))
    with pytest.raises(ForbiddenError):
        await reconciliation_routes.read_event_lineage("evt-1", _request("t1", permissions=[]))

    # A read-only caller can use all three: reconciliation is a derivation, not a write.
    reader = ["read"]
    assert (await reconciliation_routes.read_reconciliation_report(
        _request("t1", permissions=reader), provider_id=None, kind=None, limit=100
    ))["data"]["reconciliation_known"] is True
    assert (await reconciliation_routes.read_pipeline_health(
        _request("t1", permissions=reader)
    ))["data"]["pipeline"]["tenant_id"] == "t1"
    assert (await reconciliation_routes.read_event_lineage(
        "evt-1", _request("t1", permissions=reader)
    ))["data"]["lineage"]["source_event_id"] == "evt-1"


async def test_report_is_scoped_to_the_requesting_tenant(monkeypatch):
    await _seed("t1", source_event_id="e1")
    await _seed("t2", source_event_id="e2", tool_name="other-tool", provider="acme")
    stub = _use(monkeypatch, {
        "t1": [_evidence(capability_id="cap-t1")],
        "t2": [_evidence(capability_id="cap-t2")],
    })

    t1 = (await reconciliation_routes.read_reconciliation_report(
        _request("t1"), provider_id=None, kind=None, limit=100
    ))["data"]
    ids = {i["capability_id"] for i in t1["items"]}
    assert "cap-t1" in ids
    assert "cap-t2" not in ids
    assert t1["coverage"]["capabilities_examined"] == 1
    assert {c["tenant_id"] for c in stub.calls} == {"t1"}


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE RECONCILIATION — THE WIRING PROOF
# ══════════════════════════════════════════════════════════════════════════════
# `AgenticReconciliationService.pipeline_health` / `.lineage` have no live caller anywhere
# in the product today. These tests prove the route handlers reach the real service.

async def test_pipeline_health_route_reaches_the_agentic_service():
    resp = await reconciliation_routes.read_pipeline_health(_request("t1"))
    pipeline = resp["data"]["pipeline"]

    assert pipeline["tenant_id"] == "t1"
    # Shape produced by AgenticReconciliationService.pipeline_health, passed through
    # verbatim rather than reimplemented.
    for key in ("bronze_observations", "silver_facts", "canonical_activities", "outbox", "health"):
        assert key in pipeline
    assert pipeline["observation_only"] is True
    # The disclosure this lane adds at its own boundary: "healthy" here is the absence of
    # failure counters, not evidence of a working pipeline.
    assert "not the same as a healthy" in resp["data"]["verdict_basis"]


async def test_lineage_route_reaches_the_agentic_service():
    resp = await reconciliation_routes.read_event_lineage("evt-42", _request("t1"))
    lineage = resp["data"]["lineage"]

    assert lineage["source_event_id"] == "evt-42"
    for key in ("complete", "bronze_count", "silver_count", "canonical_activity_count", "gaps"):
        assert key in lineage
    # Nothing was ingested for this id, so every tier reports a gap rather than silence.
    assert "missing_bronze" in lineage["gaps"]
    assert lineage["complete"] is False
    assert resp["data"]["verdict_basis"]


async def test_lineage_is_tenant_scoped_and_not_an_existence_oracle():
    mine = (await reconciliation_routes.read_event_lineage("evt-42", _request("t1")))["data"]
    theirs = (await reconciliation_routes.read_event_lineage("evt-42", _request("t2")))["data"]
    assert mine["lineage"]["gaps"] == theirs["lineage"]["gaps"]
