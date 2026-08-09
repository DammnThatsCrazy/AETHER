"""Operator cross-tenant credential view + envelope honesty (sec26/sec27).

Guards three productization gaps:

1. **Cross-tenant operator credential view** — a verified Kyber operator can
   list every tenant's credential slot states (environment, lifecycle state,
   credential version, last test, activation/revocation timestamps) WITHOUT
   ever receiving a secret: no plaintext, no ciphertext, no data key. A regular
   Aether tenant — even an admin — is denied (403).
2. **demotion_reason** — the launch-readiness model records and surfaces the
   LAST automatic-demotion reason + timestamp, and the operator envelope reads
   it from the readiness record (None when nothing was demoted).
3. **Operational-envelope honesty** — worker health is a genuine tri-state
   (no supervisor bound -> "observed: false, live: null", never a fabricated
   zero); cursor ages / dead letters / reconciliation / repair / activation /
   audit all come from real sources and report None/unknown when a source has
   produced no signal.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from shared.store import reset_in_memory_stores as reset_shared_stores  # noqa: E402

SECRET_A = "whsec_opaque_secret_value_alpha_123"
SECRET_B = "ak_live_probe_secret_beta_456"
T1, T2 = "tenant-op-alpha", "tenant-op-beta"
P, E, S = "coinbase", "sandbox", "webhook_signing_secret"
APIKEY = "onramp_api_key"


def _reset() -> None:
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    reset_shared_stores()


@pytest.fixture(autouse=True)
def _autoreset():
    _reset()
    yield
    _reset()


def _secret_fields() -> tuple[str, ...]:
    return ("value", "encrypted_value", "encrypted_data_key", "secret", "plaintext")


# ── cross-tenant operator credential view: secrets never leak ──────────────

@pytest.mark.asyncio
async def test_collect_credential_slot_states_never_leaks_secrets():
    from services.providers.credentials.authority import CredentialAuthority
    from services.providers.credentials.operator_view import collect_credential_slot_states

    authority = CredentialAuthority()
    await authority.create_pending(T1, P, E, S, SECRET_A, created_by="operator")
    await authority.activate(T1, P, E, S, credential_version=1, actor="operator")
    await authority.create_pending(T2, P, E, APIKEY, SECRET_B, created_by="operator")

    result = await collect_credential_slot_states()
    assert result["tenant_count"] == 2
    assert result["slot_count"] == 2
    assert result["by_state"].get("active") == 1
    assert result["by_state"].get("pending") == 1

    blob = json.dumps(result)
    assert SECRET_A not in blob
    assert SECRET_B not in blob

    for item in result["items"]:
        assert item["tenant_id"] in (T1, T2)
        for view in item["slot_states"]:
            for forbidden in _secret_fields():
                assert forbidden not in view, f"secret field {forbidden!r} leaked in operator view"
            assert view["slot_name"] in (S, APIKEY)
            assert view["state"] in ("active", "pending")
            assert view["credential_version"] >= 1
            assert view["environment"] == "sandbox"
            assert "provider" in view


@pytest.mark.asyncio
async def test_collect_excludes_tombstoned_slots():
    from services.providers.credentials.authority import CredentialAuthority
    from services.providers.credentials.operator_view import collect_credential_slot_states

    authority = CredentialAuthority()
    await authority.create_pending(T1, P, E, S, SECRET_A, created_by="admin")
    await authority.activate(T1, P, E, S, credential_version=1, actor="admin")
    await authority.delete(T1, P, E, S, actor="admin")

    result = await collect_credential_slot_states()
    assert result["slot_count"] == 0
    assert result["tenant_count"] == 0
    assert result["by_state"] == {}


@pytest.mark.asyncio
async def test_tenant_credential_slot_states_groups_by_environment_and_state():
    from services.providers.credentials.authority import CredentialAuthority
    from services.providers.credentials.operator_view import tenant_credential_slot_states

    authority = CredentialAuthority()
    await authority.create_pending(T1, P, E, S, SECRET_A, created_by="admin")

    view = await tenant_credential_slot_states(T1)
    assert view["tenant_id"] == T1
    assert view["slot_count"] == 1
    assert view["by_state"].get("pending") == 1
    assert view["by_environment"]["sandbox"][0]["slot_name"] == S

    empty = await tenant_credential_slot_states("no-such-tenant")
    assert empty["slot_count"] == 0
    assert empty["by_state"] == {}
    assert empty["by_environment"] == {}


# ── HTTP gate: operator allowed, every other tenant denied ─────────────────

class _Tenant:
    def __init__(self, permissions: list[str]) -> None:
        self.tenant_id = "acting-tenant"
        self.user_id = "actor-1"
        self.role = None
        self.permissions = list(permissions)

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions

    def require_permission(self, perm: str) -> None:
        return None


def _credential_client(tenant: _Tenant) -> TestClient:
    from services.providers.credentials.routes import router

    app = FastAPI()

    @app.middleware("http")
    async def _tenant_middleware(request: Request, call_next):
        request.state.tenant = tenant
        return await call_next(request)

    app.include_router(router)
    return TestClient(app)


@pytest.mark.asyncio
async def test_operator_slot_overview_denies_non_operator():
    from services.providers.credentials.authority import CredentialAuthority

    await CredentialAuthority().create_pending(T1, P, E, S, SECRET_A, created_by="admin")

    client = _credential_client(_Tenant([]))
    resp = client.get("/v1/providers/credentials/operator/slots")
    assert resp.status_code == 403
    assert "Kyber operator access required" in resp.text


@pytest.mark.asyncio
async def test_operator_slot_overview_allows_operator_and_hides_secrets():
    from services.providers.credentials.authority import CredentialAuthority

    await CredentialAuthority().create_pending(T1, P, E, S, SECRET_A, created_by="admin")

    client = _credential_client(_Tenant(["kyber:operator"]))
    resp = client.get("/v1/providers/credentials/operator/slots")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tenant_count"] == 1
    assert data["slot_count"] == 1
    assert SECRET_A not in resp.text
    assert "encrypted_value" not in resp.text
    assert "encrypted_data_key" not in resp.text


@pytest.mark.asyncio
async def test_operator_tenant_slots_allows_operator_and_hides_secrets():
    from services.providers.credentials.authority import CredentialAuthority

    await CredentialAuthority().create_pending(T1, P, E, S, SECRET_A, created_by="admin")

    client = _credential_client(_Tenant(["kyber:operator"]))
    resp = client.get(f"/v1/providers/credentials/operator/tenants/{T1}/slots")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tenant_id"] == T1
    assert data["slot_count"] == 1
    assert SECRET_A not in resp.text


# ── demotion_reason in the readiness model + operator surface ──────────────

@pytest.mark.asyncio
async def test_readiness_demotion_reason_recorded_and_surfaced():
    from services.tenant_readiness.service import TenantLaunchReadiness

    readiness = TenantLaunchReadiness()
    stored = await readiness.record(
        T1,
        {"tenant_created": True, "api_key_issued": True},
        demotion_reason="credential_invalid_revalidation",
        demotion_at="2026-08-09T00:00:00+00:00",
    )
    assert stored["demotion_reason"] == "credential_invalid_revalidation"
    assert stored["demotion_at"] == "2026-08-09T00:00:00+00:00"

    fetched = await readiness.get(T1)
    assert fetched["demotion_reason"] == "credential_invalid_revalidation"
    assert fetched["demotion_at"] == "2026-08-09T00:00:00+00:00"
    assert fetched["ready"] is False  # only 2 of the 25 gates passed

    evaluation = readiness.evaluate(T1, {})
    assert "demotion_reason" in evaluation
    assert "demotion_at" in evaluation
    assert evaluation["demotion_reason"] is None
    assert evaluation["demotion_at"] is None


@pytest.mark.asyncio
async def test_envelope_demotion_reads_readiness_record():
    from services.kyber_operator.routes import _envelope_demotion
    from services.tenant_readiness.service import TenantLaunchReadiness

    assert (await _envelope_demotion(T1))["demotion_reason"] is None

    await TenantLaunchReadiness().record(
        T1, {}, demotion_reason="auto_demoted_revalidation_failed",
        demotion_at="2026-08-09T01:00:00+00:00",
    )
    state = await _envelope_demotion(T1)
    assert state["demotion_reason"] == "auto_demoted_revalidation_failed"
    assert state["demotion_at"] == "2026-08-09T01:00:00+00:00"


# ── operational-envelope honesty (never fabricated zeros) ──────────────────

def test_envelope_workers_honest_unknown_without_supervisor():
    from services.kyber_operator.routes import _envelope_workers
    from shared.supervisor_handle import clear_worker_supervisor

    clear_worker_supervisor()
    state = _envelope_workers()
    assert state["observed"] is False
    assert state["live"] is None
    assert state["worker_count"] == 0


def test_envelope_workers_live_false_when_workers_exist_but_none_live():
    from services.kyber_operator.routes import _envelope_workers
    from shared.supervisor_handle import clear_worker_supervisor, set_worker_supervisor

    class _FakeSupervisor:
        def status(self):
            return {
                "w1": {"state": "failed", "heartbeat_age_s": None,
                       "last_success_at": None, "dlq_depth": None,
                       "consumer_lag": None, "oldest_pending_age_s": None},
            }

    set_worker_supervisor(_FakeSupervisor())
    try:
        state = _envelope_workers()
        assert state["observed"] is True
        assert state["live"] is False
        assert state["worker_count"] == 1
        assert state["dead_letter_depth"] is None  # no telemetry -> None, not 0
    finally:
        clear_worker_supervisor()


def test_envelope_workers_live_true_with_fresh_heartbeat():
    from services.kyber_operator.routes import _envelope_workers
    from shared.supervisor_handle import clear_worker_supervisor, set_worker_supervisor

    class _FakeLive:
        def status(self):
            return {
                "w1": {"state": "running", "heartbeat_age_s": 2.0,
                       "last_success_at": "2026-08-09T00:00:00+00:00",
                       "dlq_depth": 0, "consumer_lag": 1,
                       "oldest_pending_age_s": 3.5},
            }

    set_worker_supervisor(_FakeLive())
    try:
        state = _envelope_workers()
        assert state["observed"] is True
        assert state["live"] is True
        assert state["worker_count"] == 1
        assert state["dead_letter_depth"] == 0
        assert state["consumer_lag"] == 1.0
        assert state["last_success_at"] == "2026-08-09T00:00:00+00:00"
    finally:
        clear_worker_supervisor()


def test_age_seconds_honest_unknown_on_unparseable():
    from datetime import datetime, timezone

    from services.kyber_operator.routes import _age_seconds

    now = datetime.now(timezone.utc)
    assert _age_seconds(None, now) is None
    assert _age_seconds("not-a-date", now) is None
    age = _age_seconds(now.isoformat(), now)
    assert age is not None and age >= 0.0


@pytest.mark.asyncio
async def test_envelope_sections_do_not_fabricate_zero():
    from services.kyber_operator.routes import _operational_envelope_sections
    from services.tenant_readiness.service import LAUNCH_READINESS_CHECKS
    from shared.supervisor_handle import clear_worker_supervisor

    clear_worker_supervisor()
    sections = await _operational_envelope_sections("no-such-tenant")

    assert sections["workers"]["observed"] is False
    assert sections["workers"]["live"] is None

    assert sections["credentials"]["slot_count"] == 0
    assert sections["providers"]["checkpoint_count"] == 0
    assert sections["providers"]["reconciliation_conflicts_total"] == 0
    assert sections["reconciliation"]["unresolved_count"] == 0
    assert sections["reconciliation"]["latest"] is None
    assert sections["audit"]["count"] == 0
    assert sections["audit"]["latest"] is None
    assert sections["repair"]["run_count"] == 0
    assert sections["repair"]["latest"] is None
    assert sections["activation"]["state"] is None
    assert sections["activation"]["history_count"] == 0
    assert sections["demotion"]["demotion_reason"] is None
    assert sections["demotion"]["demotion_at"] is None

    # No readiness record yet -> the real all-pending evaluation, not a zero.
    assert sections["readiness"]["observed"] is False
    assert sections["readiness"]["ready"] is False
    assert sections["readiness"]["blocking_count"] == len(LAUNCH_READINESS_CHECKS)
