"""Stream P-B2 — Olympus-internal intelligence authority tests.

No ``olympus_superuser``; authority derives from purpose + capabilities. Purpose
allowlist denies product-analytics raw tenant access and allows
benchmark-analysis on generalized material. Unknown scope / purpose → deny.
"""
import types
from enum import Enum

import pytest

from repositories.repos import reset_in_memory_stores
from services.rights_authority import olympus as olympus_mod

pytestmark = pytest.mark.asyncio


class _FakeRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

    async def record(self, row: dict) -> dict:
        rid = row.get("decision_id") or row.get("id")
        self._store[rid] = dict(row)
        return dict(row)

    async def get(self, rid: str):
        return self._store.get(rid)

    async def update_state(self, rid: str, data: dict) -> dict:
        if rid in self._store:
            self._store[rid].update(dict(data))
        return dict(self._store.get(rid) or {})

    async def list_for_tenant(self, tenant_id, limit=100, offset=0, extra=None):
        rows = [r for r in self._store.values() if r.get("tenant_id") == tenant_id]
        return rows[offset:offset + limit]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_in_memory_stores()
    repos = types.SimpleNamespace(
        rights_decision_repository=_FakeRepo(),
        rights_lineage_repository=_FakeRepo(),
        rights_impact_repository=_FakeRepo(),
    )
    monkeypatch.setattr(olympus_mod, "_pb1_repositories", lambda: repos)
    yield repos
    reset_in_memory_stores()


def _request(purpose, data_classes, tenants=None, scope=""):
    return olympus_mod.KyberIntelligenceRequest(
        operator_id="op_1",
        role="olympus_operator",
        purpose=purpose,
        requested_tenants=list(tenants or []),
        requested_scope=scope,
        requested_data_classes=list(data_classes),
        requested_actions=["read"],
    )


async def test_product_analytics_raw_tenant_access_denied():
    authority = olympus_mod.olympus_internal_authority
    decision = await authority.authorize(
        _request(
            "product_analytics",
            data_classes=["raw.scope_tenant_local"],
            tenants=["t1"],
        )
    )
    assert decision.allowed is False
    assert "raw_data_requires_generalization" in decision.reason_codes
    assert "tenant_scope_not_allowed" in decision.reason_codes


async def test_benchmark_analysis_on_generalized_material_allowed():
    authority = olympus_mod.olympus_internal_authority
    decision = await authority.authorize(
        _request(
            "benchmark_analysis",
            data_classes=["generalized.benchmark"],
        )
    )
    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert "generalized.benchmark" in decision.allowed_data_classes


async def test_unknown_purpose_denied():
    authority = olympus_mod.olympus_internal_authority
    decision = await authority.authorize(
        _request("exfiltrate_all_tenants", data_classes=["generalized.benchmark"])
    )
    assert decision.allowed is False
    assert "unknown_purpose" in decision.reason_codes


async def test_unknown_scope_denied_for_scope_owned_purpose():
    authority = olympus_mod.olympus_internal_authority
    decision = await authority.authorize(
        _request(
            "incident_response",
            data_classes=["raw.scope_tenant_local"],
            tenants=["t1"],
            scope="not_a_real_scope",
        )
    )
    assert decision.allowed is False
    assert "unknown_scope" in decision.reason_codes


async def test_grants_must_confirm_cross_tenant_raw_disclosure():
    authority = olympus_mod.olympus_internal_authority
    grant = types.SimpleNamespace(
        disclosure_authority=types.SimpleNamespace(
            cross_tenant_identifiable=False,  # does NOT permit cross-tenant raw
            generalized_cross_tenant=True,
        ),
        source_use=types.SimpleNamespace(olympus_baseline=True),
    )
    decision = await authority.authorize(
        _request(
            "security_research",
            data_classes=["raw.scope_tenant_local"],
            tenants=["t1", "t2"],
            scope="security",
        ),
        grant_records=[grant],
    )
    assert decision.allowed is False
    assert "cross_tenant_raw_not_authorized" in decision.reason_codes


async def test_filter_graph_of_graphs_restricts_to_authorized_refs():
    (kept, decision) = await olympus_mod.filter_graph_of_graphs_query(
        _request("benchmark_analysis", data_classes=["generalized.benchmark"]),
        [
            {"artifact_ref": "gart_a", "data_class": "generalized.benchmark",
             "generalized": True},
            {"artifact_ref": "gart_b", "data_class": "raw.scope_tenant_local",
             "tenant_id": "t9", "tenant_identifiable": True},
            {"artifact_ref": "gart_c", "data_class": "generalized.benchmark",
             "generalized": True},
        ],
    )
    assert decision.allowed is True
    assert [r["artifact_ref"] for r in kept] == ["gart_a", "gart_c"]


async def test_purpose_allowlist_derived_from_olympus_purpose_enum():
    class FakeOlympusPurpose(str, Enum):
        PLATFORM_RESEARCH = "platform_research"
        MODEL_IMPROVEMENT = "model_improvement"
        SECURITY_RESEARCH = "security_research"
        FRAUD_RESEARCH = "fraud_research"
        RESOLVER_CALIBRATION = "resolver_calibration"
        ONTOLOGY_RESEARCH = "ontology_research"
        PRODUCT_ANALYTICS = "product_analytics"
        BENCHMARK_ANALYSIS = "benchmark_analysis"
        SUPPORT_INVESTIGATION = "support_investigation"
        INCIDENT_RESPONSE = "incident_response"

    fake_models = types.ModuleType("services.integrations.data_rights.models")
    fake_models.OlympusPurpose = FakeOlympusPurpose
    olympus_mod._pa_models = lambda: fake_models  # type: ignore[assignment]
    allowlist = olympus_mod.olympus_purpose_allowlist()
    assert set(allowlist) == set(olympus_mod.PURPOSE_ALLOWLIST)
    assert len(allowlist) == 10
