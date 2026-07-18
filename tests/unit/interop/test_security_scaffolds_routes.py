"""Security snapshot hashing/drift, scaffold honesty, and route gates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from services.interop.providers import INTEROP_PROVIDERS
from services.interop.security import SecurityPolicyService, policy_content_hash

TENANT = "t-interop-a"
OTHER_TENANT = "t-interop-b"

_FLAGS_ON = SimpleNamespace(
    ingestion_enabled=True, lifecycle_enabled=True, adapters_enabled=True,
    layerzero_enabled=True, graph_enabled=True, profile360_enabled=True,
    api_enabled=True, noesis_enabled=True, kyber_enabled=True,
)
_FLAGS_OFF = SimpleNamespace(
    ingestion_enabled=False, lifecycle_enabled=False, adapters_enabled=False,
    layerzero_enabled=False, graph_enabled=False, profile360_enabled=False,
    api_enabled=False, noesis_enabled=False, kyber_enabled=False,
)

_POLICY = {
    "verification_model": "external_verifier_set",
    "required_verifier_ids": ["dvn-b", "dvn-a"],
    "optional_verifier_ids": [],
    "optional_threshold": None,
    "confirmations_required": 15,
    "delivery_actor_ids": ["exec-1"],
    "module_addresses": {"send_library": "0xsend", "receive_library": "0xrecv"},
}


# ── Security snapshots ───────────────────────────────────────────────────────

def test_content_hash_is_order_insensitive_and_deterministic():
    reordered = {
        **_POLICY,
        "required_verifier_ids": ["dvn-a", "dvn-b"],
        "module_addresses": {"receive_library": "0xrecv", "send_library": "0xsend"},
    }
    assert policy_content_hash(_POLICY) == policy_content_hash(reordered)
    changed = {**_POLICY, "confirmations_required": 20}
    assert policy_content_hash(_POLICY) != policy_content_hash(changed)


async def test_snapshot_idempotency_and_drift_events():
    service = SecurityPolicyService()
    first = await service.snapshot_policy(TENANT, "layerzero_v2", "path-1", _POLICY)
    assert first["inserted"] and not first["changed_from_previous"]

    duplicate = await service.snapshot_policy(TENANT, "layerzero_v2", "path-1", _POLICY)
    assert duplicate["inserted"] is False
    assert duplicate["emitted_events"] == []

    changed = await service.snapshot_policy(
        TENANT, "layerzero_v2", "path-1",
        {**_POLICY, "required_verifier_ids": ["dvn-a", "dvn-b", "dvn-c"]},
    )
    assert changed["inserted"] and changed["changed_from_previous"]
    names = [e["event_name"] for e in changed["emitted_events"]]
    assert "interop_security_policy_changed" in names

    drift = await service.path_drift(TENANT, "path-1")
    assert drift["distinct_policies"] == 2


# ── Scaffold honesty ─────────────────────────────────────────────────────────

def test_no_provider_claims_live_status():
    """Every first-release provider is credential-gated — none remains scaffolded
    and none falsely claims provider-live without evidence."""
    for provider_id, adapter in INTEROP_PROVIDERS.items():
        status = adapter.descriptor()["implementation_status"]
        assert status == "credential_gated", (provider_id, status)


async def test_credential_gated_providers_guard_unwired_scan():
    """Every non-LayerZero provider is credential-gated: a live scan without a
    wired RPC client fails closed (NotImplementedError), while decode_log handles
    an empty/undecodable log gracefully (returns None) rather than feigning the
    decoder is unimplemented."""
    for provider_id, adapter in INTEROP_PROVIDERS.items():
        if provider_id == "layerzero_v2":
            continue
        with pytest.raises(NotImplementedError):
            await adapter.scan(None)
        assert adapter.decode_log({"topics": []}) is None


def test_layerzero_is_credential_gated_with_complete_decode():
    adapter = INTEROP_PROVIDERS["layerzero_v2"]
    descriptor = adapter.descriptor()
    assert descriptor["implementation_status"] == "credential_gated"
    assert "payload_decoding" in descriptor["capabilities"]


# ── Routes ───────────────────────────────────────────────────────────────────

class _FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.is_platform_admin = False

    def require_permission(self, perm: str) -> None:
        return None


def _build_app(tenant_id: str) -> TestClient:
    from services.interop.routes import router

    app = FastAPI()

    @app.exception_handler(PermissionError)
    async def _perm(request, exc):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    app.include_router(router)

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.tenant = _FakeTenant(tenant_id)
        return await call_next(request)

    return TestClient(app)


def _observation(correlation_key: str = "lz2:0xroute", phase: str = "sent") -> dict:
    return {
        "provider_kind": "layerzero_v2",
        "provider_id": "layerzero_v2",
        "correlation_key": correlation_key,
        "phase": phase,
        "endpoint_ref": {"network_id": "ethereum-mainnet", "block_number": "100"},
        "source_network_id": "ethereum-mainnet",
        "destination_network_id": "arbitrum-mainnet",
        "observed_at": "2026-07-08T12:00:00+00:00",
    }


def test_flag_off_returns_404(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "interop", _FLAGS_OFF)
    client = _build_app(TENANT)
    assert client.get("/v1/interoperability/messages").status_code == 404


def test_intake_detail_and_tenant_plus_public_scoping(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "interop", _FLAGS_ON)

    client_a = _build_app(TENANT)
    created = client_a.post("/v1/interoperability/observations", json=_observation())
    assert created.status_code == 201, created.text
    message_id = created.json()["interop_message_id"]

    detail = client_a.get(f"/v1/interoperability/messages/{message_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["message"]["status"] == "source_confirmed"
    assert len(body["transitions"]) == 1

    # Public-scope rows are visible to every tenant...
    public_client = _build_app("public")
    public_client.post(
        "/v1/interoperability/observations", json=_observation("lz2:0xpublic"),
    )
    listed_a = client_a.get("/v1/interoperability/messages")
    keys = {m["correlation_key"] for m in listed_a.json()["items"]}
    assert {"lz2:0xroute", "lz2:0xpublic"} <= keys

    # ...but tenant rows never cross tenants.
    client_b = _build_app(OTHER_TENANT)
    listed_b = client_b.get("/v1/interoperability/messages")
    keys_b = {m["correlation_key"] for m in listed_b.json()["items"]}
    assert "lz2:0xroute" not in keys_b
    assert "lz2:0xpublic" in keys_b


def test_execution_claim_and_unknown_phase_rejected(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "interop", _FLAGS_ON)
    client = _build_app(TENANT)

    executed = _observation("lz2:0xexec")
    executed["execution_by_aether"] = True
    assert client.post("/v1/interoperability/observations", json=executed).status_code == 422

    unknown = _observation("lz2:0xphase", phase="teleported")
    assert client.post("/v1/interoperability/observations", json=unknown).status_code == 422


def test_providers_endpoint_reports_honest_statuses(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "interop", _FLAGS_ON)
    client = _build_app(TENANT)
    providers = client.get("/v1/interoperability/providers").json()["items"]
    statuses = {p["provider_id"]: p["implementation_status"] for p in providers}
    assert statuses["layerzero_v2"] == "credential_gated"
    assert all(s in ("scaffolded", "credential_gated") for s in statuses.values())
