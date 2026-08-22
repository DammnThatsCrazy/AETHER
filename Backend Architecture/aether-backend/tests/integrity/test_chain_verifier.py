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
    """An Olympus operator: holds the dedicated ``kyber:operator`` grant that
    ``require_kyber_operator`` recognises. A plain tenant admin does NOT hold it,
    so the cross-tenant chain-verification route rejects tenant admins (N4)."""

    tenant_id = "olympus_ops"
    user_id = "u-olympus_ops"
    permissions = ["kyber:operator", "admin"]

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def require_permission(self, permission: str) -> None:  # noqa: D401
        if permission not in self.permissions:
            from shared.common.common import ForbiddenError

            raise ForbiddenError(f"missing {permission}")


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


# ── N4: cross-tenant route requires an operator, not a tenant admin ────────────

class _NonOperatorTenant:
    """A plain Aether tenant admin: holds the legacy ``admin`` permission but NOT
    the ``kyber:operator`` grant, and its id is not an operator tenant id. The
    cross-tenant chain-verification route must reject it (N4) — a tenant admin
    could otherwise read every tenant's id/failure detail and overwrite another
    tenant's recorded verification status."""

    tenant_id = "aether_tenant_admin"
    user_id = "u-aether_tenant_admin"
    permissions = ["admin"]

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def require_permission(self, permission: str) -> None:
        if permission not in self.permissions:
            from shared.common.common import ForbiddenError

            raise ForbiddenError(f"missing {permission}")


def _client_for(tenant_obj) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = tenant_obj
        return await call_next(request)

    from services.integrity.routes import router

    app.include_router(router)
    return TestClient(app)


def test_endpoint_rejects_tenant_admin_non_operator():
    """A legacy ``admin`` tenant (not a Kyber operator) is Forbidden on this
    cross-tenant surface — both the aggregate and the ``?tenant_id=`` verify."""
    _seed_chain("victim_tenant", n=3)
    client = _client_for(_NonOperatorTenant())

    agg = client.get("/v1/security/ledger/chain-verification")
    assert agg.status_code == 403

    live = client.get(
        "/v1/security/ledger/chain-verification", params={"tenant_id": "victim_tenant"}
    )
    assert live.status_code == 403


# ── N15: stored prev_hash backlink is validated, not just the integrity hash ──

@pytest.mark.asyncio
async def test_backlink_tamper_reported_even_when_hash_walk_passes():
    """Rewriting only a row's stored ``prev_hash`` leaves every re-derived
    integrity hash valid (the walk advances on the stored integrity_hash), so the
    envelope-only walk would pass — but the linkage the chain columns claim is
    broken, and must be reported (N15)."""
    _seed_chain("t_backlink", n=3)
    # Tamper ONLY the backlink of the middle row; its integrity_hash is untouched.
    _IN_MEMORY_STORES[_BRONZE]["t_backlink:evt-1:1.0"]["prev_hash"] = "FORGED-BACKLINK"
    result = await chain_verifier.verify_tenant_chain("t_backlink")
    assert result.verified is False
    assert "evt-1:1.0" in result.broken_record_ids


# ── N6: typed Bronze columns are cross-checked against the data envelope ───────

def _pg_rec(seq: int, **overrides) -> dict:
    """A Postgres-record-shaped dict (supports rec[col]) with matching typed
    columns and ``data`` envelope, before any tamper override."""
    envelope = {
        "tenant_id": "t_pg",
        "event_id": f"evt-{seq}",
        "schema_version": "1.0",
        "event_type": "page_view",
        "event_timestamp": "2026-08-08T00:00:00+00:00",
        "payload_hash": f"ph-{seq}",
        "prev_hash": None,
        "integrity_hash": f"ih-{seq}",
    }
    rec = {
        **envelope,
        "data": dict(envelope),
        "created_at": "2026-08-08T01:00:00+00:00",
    }
    rec.update(overrides)
    return rec


def test_typed_envelope_match_is_not_divergence():
    row = chain_verifier._augment_pg_row(_pg_rec(0))
    assert chain_verifier._TYPED_SIDECAR in row
    assert chain_verifier._typed_envelope_divergence(row) is False


def test_typed_column_edited_without_envelope_is_divergence():
    """A typed ``event_type`` (or payload_hash/integrity_hash) edited while the
    duplicated ``data`` envelope stays unchanged is tamper the envelope-only hash
    cannot see (N6)."""
    rec = _pg_rec(0, event_type="silently_changed")  # typed != envelope
    row = chain_verifier._augment_pg_row(rec)
    assert chain_verifier._typed_envelope_divergence(row) is True


def test_corrupt_envelope_scalar_is_flagged_not_raised():
    """A ``data`` column overwritten into a scalar must not raise and must be
    caught as divergence (the reconstructed envelope lacks the typed values)."""
    rec = _pg_rec(0, data=42)  # non-str, non-dict scalar
    row = chain_verifier._augment_pg_row(rec)  # must not raise
    assert chain_verifier._typed_envelope_divergence(row) is True


# ── N7: append-only regression / vanished chain vs prior recorded state ───────

async def _record_prior(tenant_id: str, *, rows: int, tail: str) -> None:
    await get_store(_STATUS).set(
        tenant_id,
        {
            "tenant_id": tenant_id,
            "verified": True,
            "rows_scanned": rows,
            "max_rows_scanned": rows,
            "tail_hash": tail,
            "chains_verified": 1,
            "broken_record_ids": [],
        },
    )


@pytest.mark.asyncio
async def test_append_only_row_shrink_is_regression():
    """Bronze only grows; a later pass with fewer rows than the recorded
    high-watermark lost rows — a truncation the internally-valid survivors hide."""
    _seed_chain("t_shrink", n=3)
    await _record_prior("t_shrink", rows=5, tail="OLD-TAIL")
    result = await chain_verifier.verify_tenant_chain("t_shrink")
    assert result.verified is False
    assert any(str(b).startswith("chain_regressed") for b in result.broken_record_ids)


@pytest.mark.asyncio
async def test_recorded_tail_deletion_is_regression():
    """Same row count but the previously recorded tail hash is gone from the
    chain → the tail was rewritten/deleted (N7)."""
    _seed_chain("t_tail", n=3)
    await _record_prior("t_tail", rows=3, tail="TAIL-THAT-NO-LONGER-EXISTS")
    result = await chain_verifier.verify_tenant_chain("t_tail")
    assert result.verified is False
    assert any("tail_missing" in str(b) for b in result.broken_record_ids)


@pytest.mark.asyncio
async def test_stable_chain_second_pass_has_no_false_regression():
    """Guard: an unchanged chain verified twice must stay green — the regression
    check must not false-positive on a normal steady state."""
    _seed_chain("t_stable", n=3)
    await chain_verifier.run_verification_pass()  # records max_rows=3 + real tail
    result = await chain_verifier.verify_tenant_chain("t_stable")
    assert result.verified is True
    assert result.broken_record_ids == []


@pytest.mark.asyncio
async def test_vanished_chain_flagged_and_recorded_failed():
    """A tenant that had a chain last pass but whose rows are all gone this pass
    disappears from list_tenants_with_chain(); without reconciliation its old
    green status would linger forever (N7)."""
    await _record_prior("t_gone", rows=3, tail="T")
    _seed_chain("t_present", n=2)
    summary = await chain_verifier.run_verification_pass()
    assert "t_gone" in summary["vanished_tenants"]
    assert "t_gone" in summary["failed_tenants"]
    status = await get_store(_STATUS).get("t_gone")
    assert status["verified"] is False


# ── N13: a verifier exception is recorded failed + alerted, never left green ───

@pytest.mark.asyncio
async def test_verifier_exception_records_failed_and_alerts(monkeypatch):
    calls: list[dict] = []

    async def _fake_record_alert(**kwargs):
        calls.append(kwargs)
        return {"alert_id": "a", **kwargs}

    import services.agent.ops_alerts as ops_alerts

    monkeypatch.setattr(ops_alerts, "record_alert", _fake_record_alert)

    _seed_chain("t_raises", n=3)

    async def _boom(tenant_id: str):
        raise RuntimeError("data corrupted into a scalar")

    monkeypatch.setattr(chain_verifier, "verify_and_record", _boom)

    summary = await chain_verifier.run_verification_pass()
    assert "t_raises" in summary["errored_tenants"]
    assert "t_raises" in summary["failed_tenants"]

    status = await get_store(_STATUS).get("t_raises")
    assert status is not None and status["verified"] is False
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == "t_raises"
