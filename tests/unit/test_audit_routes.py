"""Tests for /v1/audit (cross-domain audit trail export)."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def audit_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.consent.audit_routes")
        importlib.reload(mod)
        # Reset shared.store-backed sources
        from shared.store import get_store
        for source in ("agent_audit", "guardrail_decisions", "extraction_runs", "audit_exports"):
            s = get_store(source)
            s._data.clear()
            s._lists.clear()
        # Reset consent repo (in-memory store inside BaseRepository)
        mod._consent_repo._store.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        user_id=f"u-{tenant_id}",
        require_permission=lambda perm: None,
        has_permission=lambda perm: True,
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant), client=None)


async def seed_records(audit_routes, tenant_id: str = "t-001"):
    """Seed each source via its real persistence layer."""
    from shared.store import get_store

    # agent_audit — list-backed, key=tenant_id
    agent_store = get_store("agent_audit")
    await agent_store.append_list(tenant_id, {
        "tenant_id": tenant_id, "task_id": "a-1", "action": "task_submitted",
        "timestamp": "2026-05-01T00:00:00+00:00",
    })
    await agent_store.append_list(tenant_id, {
        "tenant_id": tenant_id, "task_id": "a-2", "action": "task_completed",
        "timestamp": "2026-05-02T00:00:00+00:00",
    })

    # guardrail_decisions — list-backed, key=f"decisions:{tenant_id}"
    gr_store = get_store("guardrail_decisions")
    await gr_store.append_list(f"decisions:{tenant_id}", {
        "tenant_id": tenant_id, "policy_id": "p-1", "outcome": "deny",
        "timestamp": "2026-05-01T01:00:00+00:00",
    })

    # extraction_runs — set-backed
    ex_store = get_store("extraction_runs")
    await ex_store.set(f"{tenant_id}:run-1", {
        "tenant_id": tenant_id, "run_id": "run-1", "score": 42.0, "band": "yellow",
        "created_at": "2026-05-02T01:00:00+00:00",
    })

    # consent_records + consent_dsr — both via ConsentRepository
    await audit_routes._consent_repo.insert("c-1", {
        "tenant_id": tenant_id, "user_id": "u-1", "purposes": ["analytics"], "granted": True,
        "recorded_at": "2026-05-03T00:00:00+00:00",
    })
    await audit_routes._consent_repo.insert("dsr_d-1", {
        "tenant_id": tenant_id, "dsr_id": "d-1", "request_type": "access", "status": "completed",
        "submitted_at": "2026-05-03T01:00:00+00:00",
    })
    await audit_routes._consent_repo.insert("dsr_d-2", {
        "tenant_id": tenant_id, "dsr_id": "d-2", "request_type": "erasure", "status": "pending",
        "submitted_at": "2026-05-04T00:00:00+00:00",
    })


@pytest.mark.asyncio
async def test_list_trails_aggregates_all_sources(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.list_trails(make_request())
    assert res["data"]["count"] == 7
    sources_seen = {t["_source"] for t in res["data"]["trails"]}
    assert sources_seen == {
        "agent_audit", "guardrail_decisions", "extraction_runs",
        "consent_records", "consent_dsr",
    }


@pytest.mark.asyncio
async def test_list_trails_filtered_by_source(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.list_trails(make_request(), source="agent_audit")
    assert res["data"]["count"] == 2
    assert all(t["_source"] == "agent_audit" for t in res["data"]["trails"])


@pytest.mark.asyncio
async def test_consent_records_excludes_dsr(audit_routes):
    """Consent and DSR records share the same table; reader must split them."""
    await seed_records(audit_routes)
    consent = await audit_routes.list_trails(make_request(), source="consent_records")
    dsr = await audit_routes.list_trails(make_request(), source="consent_dsr")
    assert consent["data"]["count"] == 1
    assert dsr["data"]["count"] == 2


@pytest.mark.asyncio
async def test_list_trails_unknown_source_400(audit_routes):
    with pytest.raises(Exception) as exc:
        await audit_routes.list_trails(make_request(), source="bogus")
    assert "Unknown source" in str(exc.value)


@pytest.mark.asyncio
async def test_list_trails_time_filter(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.list_trails(
        make_request(), from_ts="2026-05-03T00:00:00+00:00"
    )
    sources_seen = {t["_source"] for t in res["data"]["trails"]}
    assert "agent_audit" not in sources_seen
    assert "consent_records" in sources_seen


@pytest.mark.asyncio
async def test_get_trail_finds_list_backed_entry(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.get_trail("a-1", make_request())
    assert res["data"]["_source"] == "agent_audit"
    assert res["data"]["task_id"] == "a-1"


@pytest.mark.asyncio
async def test_get_trail_finds_dsr_entry(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.get_trail("d-2", make_request())
    assert res["data"]["_source"] == "consent_dsr"


@pytest.mark.asyncio
async def test_get_trail_404(audit_routes):
    with pytest.raises(Exception) as exc:
        await audit_routes.get_trail("missing", make_request())
    assert "not found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_request_export_includes_rows_from_all_sources(audit_routes):
    await seed_records(audit_routes)
    body = audit_routes.ExportRequest(format="json", report_type="soc2")
    res = await audit_routes.request_export(body, make_request())
    assert res["data"]["row_count"] == 7
    assert res["data"]["status"] == "complete"
    assert res["data"]["per_source"]["agent_audit"] == 2
    assert res["data"]["per_source"]["guardrail_decisions"] == 1
    assert res["data"]["per_source"]["consent_dsr"] == 2
    assert "rows" in res["data"]


@pytest.mark.asyncio
async def test_request_export_invalid_format(audit_routes):
    body = audit_routes.ExportRequest(format="xml")
    with pytest.raises(Exception) as exc:
        await audit_routes.request_export(body, make_request())
    assert "Invalid format" in str(exc.value)


@pytest.mark.asyncio
async def test_list_and_get_exports(audit_routes):
    await seed_records(audit_routes)
    body = audit_routes.ExportRequest(format="json")
    created = await audit_routes.request_export(body, make_request())
    eid = created["data"]["export_id"]

    listed = await audit_routes.list_exports(make_request())
    assert listed["data"]["count"] >= 1

    fetched = await audit_routes.get_export(eid, make_request())
    assert fetched["data"]["export_id"] == eid


@pytest.mark.asyncio
async def test_soc2_report(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.soc2_report(make_request())
    assert res["data"]["report_type"] == "soc2"
    assert res["data"]["total_records"] == 7
    assert res["data"]["per_source"]["agent_audit"] == 2
    assert res["data"]["per_source"]["guardrail_decisions"] == 1


@pytest.mark.asyncio
async def test_gdpr_report_dsr_status_breakdown(audit_routes):
    await seed_records(audit_routes)
    res = await audit_routes.gdpr_report(make_request())
    assert res["data"]["report_type"] == "gdpr"
    assert res["data"]["consent_record_count"] == 1
    assert res["data"]["dsr_total"] == 2
    assert res["data"]["dsr_by_status"]["completed"] == 1
    assert res["data"]["dsr_by_status"]["pending"] == 1


@pytest.mark.asyncio
async def test_consent_records_isolated_per_tenant(audit_routes):
    await seed_records(audit_routes, tenant_id="t-001")
    await audit_routes._consent_repo.insert("c-other", {
        "tenant_id": "t-002", "user_id": "u-2", "purposes": ["marketing"],
    })
    res = await audit_routes.list_trails(make_request("t-001"), source="consent_records")
    assert res["data"]["count"] == 1
