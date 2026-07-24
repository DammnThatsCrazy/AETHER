"""Capability risk findings + blast radius (PR 2, Phase C, monoprompt §9.5).

Handlers are called directly with a fake ``Request`` — the established pattern in this
suite (``test_capability_authority_routes.py``) — so permission gates and tenant scoping
are exercised without standing up the middleware.

The load-bearing test in this file is ``test_never_observed_agent_reports_unknown_not_zero``.
Everything else is ordinary surface behaviour; that one guards the property the endpoint
exists for: an agent we have never observed must produce ``exposure_known: false`` with
``null`` counts, never ``0``. "0 capabilities exposed" is a claim about the world; when
no installation was ever recorded, the only true answer is "we do not know". The test
walks the entire response recursively and fails on any zero-valued number anywhere in it,
so a future refactor cannot reintroduce the lie through a new field.

``capability_declaration_service.digest_map`` is stubbed rather than driven through the
declarations write path, so drift behaviour here is verifiable independently of that
module's storage.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import BadRequestError, ForbiddenError

import services.agent_access_intelligence.risk_service as risk_service
import services.agent_access_intelligence.risk_routes as risk_routes
from services.agent_access_intelligence.authority_routes import (
    CapabilityAuthorizationGrant,
    grant_authorization,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.identity import artifact_digest_for
from services.agent_access_intelligence.risk_service import IDENTITY_DRIFT_CODE
from services.agent_access_intelligence.scanning import CapabilityFinding, FindingCode


class FakeProducer:
    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)


class StubDeclarations:
    """Stands in for the declarations lane so drift is driven by this test, not by that
    module's write path."""

    def __init__(self, digests: Optional[dict[str, str]] = None) -> None:
        self.digests = dict(digests or {})

    async def digest_map(self, tenant_id: str, *, limit: int = 1000) -> dict[str, str]:
        return dict(self.digests)


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
def _stub_declarations(monkeypatch):
    """No declarations on file unless a test says otherwise."""
    stub = StubDeclarations()
    monkeypatch.setattr(risk_service, "capability_declaration_service", stub)
    return stub


def _stub_scan(monkeypatch, findings_by_capability: dict[str, list[CapabilityFinding]]):
    """Replace the scanning lane with a deterministic map, so count/filter/pagination
    assertions here do not move when that module's heuristics change."""

    def _scan(records):
        out: list[CapabilityFinding] = []
        for record in records:
            out.extend(findings_by_capability.get(record.get("capability_id"), []))
        return out

    monkeypatch.setattr(risk_service, "scan_capabilities", _scan)


def _finding(code: FindingCode, capability_id: str, risk_level: str) -> CapabilityFinding:
    return CapabilityFinding(
        code=code,
        risk_level=risk_level,
        summary=f"synthetic {code.value}",
        evidence=f"evidence for {capability_id}",
        capability_id=capability_id,
    )


async def _seed(
    tenant_id: str = "t1",
    *,
    source_event_id: str = "e1",
    agent_id: Optional[str] = "agentA",
    tool_name: Optional[str] = "search",
    server_name: Optional[str] = "srvX",
    server_url: Optional[str] = None,
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
        "server_url": server_url,
        "provider": provider,
        "risk_level": "high",
    })
    return result["capability_id"]


def _zero_numbers(value: Any, path: str = "$") -> list[str]:
    """Every path in ``value`` holding a numeric zero. ``bool`` is excluded on purpose —
    ``False`` is an ``int`` in Python and ``exposure_known: false`` is the honest answer,
    not a count."""
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
# BLAST RADIUS — unknown is never zero
# ══════════════════════════════════════════════════════════════════════════════

async def test_never_observed_agent_reports_unknown_not_zero():
    await _seed()  # a populated tenant, so "empty store" is not what makes this pass
    resp = await risk_routes.read_blast_radius(
        _request("t1"), agent_id="ghost-agent", capability_id=None
    )
    data = resp["data"]

    assert data["exposure_known"] is False
    assert data["missing_inputs"], "an absent input must be named, not silently dropped"
    assert any("capability_installations" in entry for entry in data["missing_inputs"])
    assert any("ghost-agent" in entry for entry in data["missing_inputs"])

    # Every count is null. Not 0 — 0 would be a claim we have no evidence for.
    assert set(data["counts"]) == {
        "servers_reachable",
        "capabilities_exposed",
        "capabilities_authorized",
        "capabilities_unauthorized",
    }
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null when it could not be computed"

    # And nowhere else in the response either.
    assert _zero_numbers(data) == []

    assert "UNKNOWN" in data["summary"]
    assert "not zero" in data["summary"]


async def test_capability_without_server_binding_reports_unknown_not_zero():
    # provider action with no server → no installation row and no server key to join on.
    cap_id = await _seed(server_name=None, server_url=None, tool_name="transfer")
    resp = await risk_routes.read_blast_radius(
        _request("t1"), agent_id=None, capability_id=cap_id
    )
    data = resp["data"]

    assert data["exposure_known"] is False
    assert any("capability_server_binding" in e for e in data["missing_inputs"])
    assert set(data["counts"]) == {
        "agents_reaching",
        "agents_authorized",
        "agents_unauthorized",
    }
    assert all(v is None for v in data["counts"].values())
    assert _zero_numbers(data) == []


async def test_unknown_capability_id_is_unknown_exposure_not_an_existence_oracle():
    await _seed()
    mine = await risk_routes.read_blast_radius(
        _request("t2"), agent_id=None, capability_id="cap_does_not_exist"
    )
    assert mine["data"]["exposure_known"] is False
    assert any("capability_catalog" in e for e in mine["data"]["missing_inputs"])
    assert _zero_numbers(mine["data"]) == []


# ══════════════════════════════════════════════════════════════════════════════
# BLAST RADIUS — computed answers
# ══════════════════════════════════════════════════════════════════════════════

async def test_agent_blast_radius_counts_only_when_every_input_is_present():
    cap_id = await _seed(source_event_id="e1", tool_name="search")
    await _seed(source_event_id="e2", tool_name="write")  # second capability, same server

    resp = await risk_routes.read_blast_radius(
        _request("t1"), agent_id="agentA", capability_id=None
    )
    data = resp["data"]
    assert data["exposure_known"] is True
    assert data["missing_inputs"] == []
    assert data["counts"]["servers_reachable"] == 1
    assert data["counts"]["capabilities_exposed"] == 2
    # A computed zero is legitimate: we checked, and nothing was authorized.
    assert data["counts"]["capabilities_authorized"] == 0
    assert data["counts"]["capabilities_unauthorized"] == 2
    assert data["basis"] == "observed_only"
    assert "not a proof of total reach" in data["summary"]

    await grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=FakeProducer(),
    )
    after = (
        await risk_routes.read_blast_radius(
            _request("t1"), agent_id="agentA", capability_id=None
        )
    )["data"]
    assert after["counts"]["capabilities_authorized"] == 1
    assert after["counts"]["capabilities_unauthorized"] == 1
    assert [c["authorized"] for c in after["capabilities"] if c["capability_id"] == cap_id] == [True]


async def test_capability_blast_radius_lists_reaching_agents():
    cap_id = await _seed(source_event_id="e1", agent_id="agentA")
    await _seed(source_event_id="e2", agent_id="agentB")  # same server + tool

    data = (
        await risk_routes.read_blast_radius(
            _request("t1"), agent_id=None, capability_id=cap_id
        )
    )["data"]
    assert data["exposure_known"] is True
    assert data["counts"]["agents_reaching"] == 2
    assert sorted(a["agent_id"] for a in data["agents"]) == ["agentA", "agentB"]


async def test_blast_radius_is_tenant_scoped_and_requires_read():
    await _seed("t1")
    other = await risk_routes.read_blast_radius(
        _request("t2"), agent_id="agentA", capability_id=None
    )
    # t2 never observed agentA — unknown, and certainly not t1's exposure.
    assert other["data"]["exposure_known"] is False

    with pytest.raises(ForbiddenError):
        await risk_routes.read_blast_radius(
            _request("t1", permissions=[]), agent_id="agentA", capability_id=None
        )


async def test_blast_radius_requires_exactly_one_subject():
    with pytest.raises(BadRequestError):
        await risk_routes.read_blast_radius(_request("t1"), agent_id=None, capability_id=None)
    with pytest.raises(BadRequestError):
        await risk_routes.read_blast_radius(_request("t1"), agent_id="a", capability_id="c")


# ══════════════════════════════════════════════════════════════════════════════
# FINDINGS — identity drift
# ══════════════════════════════════════════════════════════════════════════════

async def test_drift_is_reported_only_for_a_digest_mismatch(_stub_declarations):
    cap_id = await _seed()
    row = await capability_catalog_service.get_capability("t1", cap_id)
    observed_digest = artifact_digest_for(row)

    # 1. No declaration → observed_only → NOT a finding.
    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    assert [i for i in data["items"] if i["code"] == IDENTITY_DRIFT_CODE] == []
    assert data["identity"]["observed_only"] == 1
    assert data["identity"]["drifted"] == 0

    # 2. Declaration whose digest agrees → declared → still NOT a finding.
    _stub_declarations.digests = {cap_id: observed_digest}
    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    assert [i for i in data["items"] if i["code"] == IDENTITY_DRIFT_CODE] == []
    assert data["identity"]["declared"] == 1

    # 3. Declaration whose digest disagrees → drifted → exactly one finding.
    _stub_declarations.digests = {cap_id: "art_something_else"}
    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    drift = [i for i in data["items"] if i["code"] == IDENTITY_DRIFT_CODE]
    assert len(drift) == 1
    assert drift[0]["capability_id"] == cap_id
    assert drift[0]["source"] == "identity"
    assert observed_digest in drift[0]["evidence"]
    assert data["identity"]["drifted"] == 1
    assert data["identity"]["observed_only"] == 0


async def test_observed_only_capabilities_never_become_findings(monkeypatch):
    _stub_scan(monkeypatch, {})
    for i in range(3):
        await _seed(source_event_id=f"e{i}", tool_name=f"tool{i}")
    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    assert data["identity"]["observed_only"] == 3
    assert data["items"] == []
    assert data["counts"]["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# FINDINGS — scoping, counts, filter, pagination
# ══════════════════════════════════════════════════════════════════════════════

async def test_findings_are_tenant_scoped(monkeypatch):
    mine = await _seed("t1", source_event_id="e1", tool_name="mine")
    theirs = await _seed("t2", source_event_id="e2", tool_name="theirs")
    _stub_scan(monkeypatch, {
        mine: [_finding(FindingCode.INSECURE_TRANSPORT, mine, "high")],
        theirs: [_finding(FindingCode.INSECURE_TRANSPORT, theirs, "high")],
    })

    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    ids = {i["capability_id"] for i in data["items"]}
    assert ids == {mine}
    assert theirs not in ids
    assert data["identity"]["capabilities_examined"] == 1

    with pytest.raises(ForbiddenError):
        await risk_routes.list_risk_findings(
            _request("t1", permissions=[]), code=None, limit=100, offset=0
        )


async def test_counts_match_the_item_list(monkeypatch, _stub_declarations):
    cap_a = await _seed(source_event_id="e1", tool_name="alpha")
    cap_b = await _seed(source_event_id="e2", tool_name="beta")
    _stub_scan(monkeypatch, {
        cap_a: [
            _finding(FindingCode.INSECURE_TRANSPORT, cap_a, "high"),
            _finding(FindingCode.PRIVATE_NETWORK_ORIGIN, cap_a, "medium"),
        ],
        cap_b: [_finding(FindingCode.INSECURE_TRANSPORT, cap_b, "high")],
    })
    _stub_declarations.digests = {cap_b: "art_mismatch"}  # + one drift finding

    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    items = data["items"]
    assert data["counts"]["total"] == len(items) == 4
    assert data["count"] == len(items)

    by_risk: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for item in items:
        by_risk[item["risk_level"]] = by_risk.get(item["risk_level"], 0) + 1
        by_code[item["code"]] = by_code.get(item["code"], 0) + 1
    assert data["counts"]["by_risk_level"] == by_risk
    assert data["counts"]["by_code"] == by_code
    assert sum(data["counts"]["by_risk_level"].values()) == data["counts"]["total"]

    # Ordered by severity: every high precedes every medium.
    levels = [i["risk_level"] for i in items]
    assert levels == sorted(levels, key=lambda lvl: {"high": 0, "medium": 1}[lvl])


async def test_code_filter_and_pagination(monkeypatch):
    cap_a = await _seed(source_event_id="e1", tool_name="alpha")
    cap_b = await _seed(source_event_id="e2", tool_name="beta")
    _stub_scan(monkeypatch, {
        cap_a: [
            _finding(FindingCode.INSECURE_TRANSPORT, cap_a, "high"),
            _finding(FindingCode.PRIVATE_NETWORK_ORIGIN, cap_a, "medium"),
        ],
        cap_b: [_finding(FindingCode.INSECURE_TRANSPORT, cap_b, "high")],
    })

    insecure = FindingCode.INSECURE_TRANSPORT.value
    filtered = (
        await risk_routes.list_risk_findings(_request("t1"), code=insecure, limit=100, offset=0)
    )["data"]
    assert filtered["counts"]["total"] == 2
    assert {i["code"] for i in filtered["items"]} == {insecure}
    assert filtered["filter"]["code"] == insecure

    # Case-insensitive: the filter accepts the caller's casing without renaming the code.
    upper = (
        await risk_routes.list_risk_findings(
            _request("t1"), code=insecure.upper(), limit=100, offset=0
        )
    )["data"]
    assert upper["counts"]["total"] == 2
    assert {i["code"] for i in upper["items"]} == {insecure}

    page_one = (
        await risk_routes.list_risk_findings(_request("t1"), code=None, limit=2, offset=0)
    )["data"]
    page_two = (
        await risk_routes.list_risk_findings(_request("t1"), code=None, limit=2, offset=2)
    )["data"]
    assert page_one["count"] == 2 and page_two["count"] == 1
    # Counts stay over the whole matching set — a page-scoped total would understate risk.
    assert page_one["counts"]["total"] == page_two["counts"]["total"] == 3
    assert page_one["offset"] == 0 and page_two["offset"] == 2
    keys = [(i["code"], i["capability_id"]) for i in page_one["items"] + page_two["items"]]
    assert len(set(keys)) == 3


async def test_real_scanner_findings_flow_through_unstubbed():
    """One end-to-end pass with the real scanning module, so the two lanes are wired
    together and not only against a stub."""
    cap_id = await _seed(server_name=None, server_url="http://example.com/mcp")
    data = (await risk_routes.list_risk_findings(_request("t1"), code=None, limit=100, offset=0))["data"]
    codes = {i["code"] for i in data["items"]}
    assert FindingCode.INSECURE_TRANSPORT.value in codes
    assert all(i["capability_id"] == cap_id for i in data["items"])
    assert all(i["source"] == "scan" for i in data["items"])
    assert data["coverage"]["sampled"] is False
