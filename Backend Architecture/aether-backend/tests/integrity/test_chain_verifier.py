"""LEDGER M3 -- Bronze truth-chain verifier + status endpoint + alert wiring.

Reliability Phase-2, Program 1 ("Truth-chain ledger"), M3.

Runs in local/in-memory mode: M2-shaped chained ``bronze_sdk_events`` rows are
built directly in the shared in-memory store and the reader
(``services/integrity/chain_verifier.py``) is exercised end to end -- intact ->
verified; tampered / deleted -> failure with a break location; status recorded;
the ``/v1/security/ledger/chain-verification`` endpoint returns the dashboard;
and a security alert is emitted (asserted) only on failure.

The rows here are chained with an INDEPENDENT literal reproduction of M2's
canonical fields (``services/ingestion/bronze_bulk.py`` ``_canonical_fields``):
an intact chain therefore only verifies if the verifier reproduces that exact
shape, so this doubles as a guard against the verifier drifting from M2.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError
from shared.integrity import hash_chain
from shared.store import get_store
from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores
from services.integrity import chain_verifier

_BRONZE = "bronze_sdk_events"
_STATUS = "ledger_chain_verification"

# The exact M2 canonical field set (services/ingestion/bronze_bulk.py). Pinned
# here independently so a drift in the verifier's mirror is caught.
_M2_CANONICAL_KEYS = {
    "event_id",
    "tenant_id",
    "schema_version",
    "event_type",
    "event_timestamp",
    "payload_hash",
}


# ── isolation ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Empty every backing store and force the in-memory (no-pool) read path."""
    reset_in_memory_stores()
    status_store = get_store(_STATUS)
    if hasattr(status_store, "_data"):
        status_store._data.clear()

    async def _no_pool():
        return None

    # Both the loader and the tenant enumerator resolve get_pool lazily from this
    # module, so patching the attribute forces the in-memory branch hermetically
    # (independent of DATABASE_URL / asyncpg in the runner).
    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    yield
    reset_in_memory_stores()
    if hasattr(status_store, "_data"):
        status_store._data.clear()


# ── M2-shaped row builders (independent of M2's ingest code) ──────────────────

def _canonical(row: dict) -> dict:
    """Independent literal copy of bronze_bulk.py M2 ``_canonical_fields``."""
    return {
        "event_id": row.get("event_id"),
        "tenant_id": row.get("tenant_id"),
        "schema_version": row.get("schema_version"),
        "event_type": row.get("event_type"),
        "event_timestamp": row.get("event_timestamp"),
        "payload_hash": row.get("payload_hash"),
    }


def _row(tenant_id: str, seq: int, *, schema_version: str = "1.0") -> dict:
    event_id = f"evt-{seq}"
    return {
        "id": f"{tenant_id}:{event_id}:{schema_version}",
        "tenant_id": tenant_id,
        "event_id": event_id,
        "schema_version": schema_version,
        "event_type": "page_view",
        "event_timestamp": f"2026-08-08T00:00:0{seq}+00:00",
        "payload_hash": f"ph-{tenant_id}-{seq}",
        "created_at": f"2026-08-08T01:00:0{seq}+00:00",
        "prev_hash": None,
        "integrity_hash": None,
    }


def _seed_chain(tenant_id: str, n: int = 3) -> list[dict]:
    """Insert ``n`` correctly-chained rows for ``tenant_id`` into the bronze store."""
    store = _IN_MEMORY_STORES.setdefault(_BRONZE, {})
    prev = ""
    rows: list[dict] = []
    for seq in range(n):
        row = _row(tenant_id, seq)
        integrity = hash_chain.compute_integrity_hash(_canonical(row), prev)
        row["prev_hash"] = prev or None
        row["integrity_hash"] = integrity
        store[row["id"]] = row
        prev = integrity
        rows.append(row)
    return rows


def _tamper_payload(tenant_id: str, seq: int, schema_version: str = "1.0") -> str:
    """Edit a chained row's content (payload_hash) without re-hashing -> break."""
    store = _IN_MEMORY_STORES[_BRONZE]
    key = f"{tenant_id}:evt-{seq}:{schema_version}"
    store[key]["payload_hash"] = "TAMPERED"
    return f"evt-{seq}:{schema_version}"


# ── verifier: intact ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intact_chain_verified():
    _seed_chain("tenant_ok", n=3)
    result = await chain_verifier.verify_tenant_chain("tenant_ok")
    assert result.verified is True
    assert result.rows_scanned == 3
    assert result.chains_verified == 1
    assert result.broken_record_ids == []
    assert result.break_location is None
    assert result.checked_at  # timestamp stamped


# ── verifier: tampered ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tampered_chain_reports_failure():
    _seed_chain("tenant_bad", n=3)
    broken_at = _tamper_payload("tenant_bad", 1)  # edit the middle row's content
    result = await chain_verifier.verify_tenant_chain("tenant_bad")
    assert result.verified is False
    assert result.rows_scanned == 3
    # Only the tampered row is flagged (verify_chain advances on the stored hash,
    # so the break does not cascade to later rows).
    assert result.broken_record_ids == [broken_at]
    assert result.break_location == broken_at


@pytest.mark.asyncio
async def test_deleted_row_reports_failure():
    _seed_chain("tenant_del", n=3)
    # Physically remove the middle row: the row after it re-derives against the
    # wrong running previous-hash and is detected as broken.
    del _IN_MEMORY_STORES[_BRONZE]["tenant_del:evt-1:1.0"]
    result = await chain_verifier.verify_tenant_chain("tenant_del")
    assert result.verified is False
    assert result.rows_scanned == 2
    assert result.break_location == "evt-2:1.0"


# ── status persistence ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_and_record_persists_status():
    _seed_chain("tenant_ok", n=2)
    _seed_chain("tenant_bad", n=3)
    _tamper_payload("tenant_bad", 1)

    summary = await chain_verifier.run_verification_pass()
    assert summary["tenants_checked"] == 2
    assert summary["verified"] == 1
    assert summary["verification_failures"] == 1
    assert summary["failed_tenants"] == ["tenant_bad"]

    dashboard = await chain_verifier.get_verification_dashboard()
    assert dashboard["verified"] == 1
    assert dashboard["verification_failures"] == 1
    assert dashboard["verified_tenants"] == ["tenant_ok"]
    assert dashboard["failing_tenants"][0]["tenant_id"] == "tenant_bad"


# ── alert wiring ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_emitted_on_failure(monkeypatch):
    calls: list[dict] = []

    async def _fake_record_alert(**kwargs):
        calls.append(kwargs)
        return {"alert_id": "alert-test", **kwargs}

    import services.agent.ops_alerts as ops_alerts

    monkeypatch.setattr(ops_alerts, "record_alert", _fake_record_alert)

    _seed_chain("tenant_bad", n=3)
    _tamper_payload("tenant_bad", 1)
    result = await chain_verifier.verify_and_record("tenant_bad")

    assert result.verified is False
    assert len(calls) == 1
    call = calls[0]
    assert call["tenant_id"] == "tenant_bad"
    assert call["severity"] == "P1"
    assert call["kind"] == "ledger_chain_integrity"
    assert call["dedupe_key"] == "ledger_chain_integrity:tenant_bad"
    assert "FAILED" in call["message"]


@pytest.mark.asyncio
async def test_no_alert_on_intact_chain(monkeypatch):
    calls: list[dict] = []

    async def _fake_record_alert(**kwargs):
        calls.append(kwargs)

    import services.agent.ops_alerts as ops_alerts

    monkeypatch.setattr(ops_alerts, "record_alert", _fake_record_alert)

    _seed_chain("tenant_ok", n=3)
    result = await chain_verifier.verify_and_record("tenant_ok")

    assert result.verified is True
    assert calls == []


# ── endpoint ──────────────────────────────────────────────────────────────────

class _OperatorTenant:
    tenant_id = "operator"

    def require_permission(self, permission: str) -> None:  # noqa: D401
        pass  # operator has every permission in this test harness


def _client() -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = _OperatorTenant()
        return await call_next(request)

    from services.integrity.routes import router

    app.include_router(router)
    return TestClient(app)


def test_endpoint_returns_aggregate_status():
    _seed_chain("tenant_ok", n=3)
    asyncio.run(chain_verifier.run_verification_pass())

    resp = _client().get("/v1/security/ledger/chain-verification")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["verified"] == 1
    assert data["verification_failures"] == 0
    assert data["verified_tenants"] == ["tenant_ok"]


def test_endpoint_live_tenant_verification_reports_break():
    _seed_chain("tenant_bad", n=3)
    _tamper_payload("tenant_bad", 1)

    resp = _client().get(
        "/v1/security/ledger/chain-verification", params={"tenant_id": "tenant_bad"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tenant_id"] == "tenant_bad"
    assert data["verified"] is False
    assert data["break_location"] == "evt-1:1.0"


# ── drift guard ───────────────────────────────────────────────────────────────

def test_verifier_canonical_fields_match_m2():
    """The verifier's canonical-field shape must equal M2's exactly."""
    sample = _row("t", 0)
    assert set(chain_verifier._bronze_canonical_fields(sample).keys()) == _M2_CANONICAL_KEYS
    assert chain_verifier._bronze_chain_partition(sample) == "t"
    assert chain_verifier._bronze_chain_sort_key(sample) == (
        sample["created_at"],
        sample["event_id"],
        sample["schema_version"],
    )
