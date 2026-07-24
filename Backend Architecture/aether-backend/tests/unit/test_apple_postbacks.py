"""Apple AdAttributionKit / SKAdNetwork postback ingestion: version-tolerant
parsing, idempotency, malformed rejection, and honest signature status.

These rows are campaign-level platform evidence (proof_level
'platform_verified') and are explicitly separate from user-level deterministic
acquisition evidence — no touchpoints are created here."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.attribution import apple_postbacks as module
from services.attribution.apple_postbacks import (
    ApplePostbackRequest,
    MalformedPostbackError,
    ingest_apple_postback,
    reduce_postback,
)
from shared.auth.auth import Role, TenantContext


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(module, "_pool", no_pool)
    module.reset_apple_postbacks_for_tests()
    yield
    module.reset_apple_postbacks_for_tests()


# ── Fixtures: valid / duplicate / malformed postbacks ────────────────────────

@pytest.fixture
def adattributionkit_postback() -> dict:
    """AdAttributionKit-style (kebab-case) postback with a signature."""

    return {
        "version": "4.0",
        "postback-id": "pb-0001",
        "ad-network-id": "example123.adattributionkit",
        "source-identifier": "3120",
        "app-id": 123456789,
        "coarse-conversion-value": "high",
        "fine-conversion-value": 42,
        "did-win": True,
        "postback-sequence-index": 0,
        "postback-environment": "sandbox",
        "attribution-signature": "MEUCIQD5eq3AragQ0nB5RjfWVzbdkOQMkVQ0Z5v...",
    }


@pytest.fixture
def duplicate_postback(adattributionkit_postback: dict) -> dict:
    """Byte-identical redelivery of the same postback (Apple retries)."""

    return dict(adattributionkit_postback)


@pytest.fixture
def malformed_postback() -> dict:
    """No postback/transaction id and no campaign identity."""

    return {"version": "4.0", "conversion-value": 7}


TENANT = TenantContext(tenant_id="tenant-a", role=Role.SERVICE)


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_reduce_is_version_tolerant_across_spellings():
    kebab = reduce_postback(
        {
            "version": "3.0",
            "transaction-id": "txn-9",
            "ad-network-id": "net.example",
            "campaign-id": 42,
            "conversion-value": "12",
            "environment": "production",
        }
    )
    camel = reduce_postback(
        {
            "version": "4.0",
            "transactionId": "txn-9",
            "adNetworkId": "net.example",
            "sourceIdentifier": "42",
            "coarseConversionValue": "medium",
            "fineConversionValue": 12,
        }
    )
    assert kebab["idempotency_key"] == camel["idempotency_key"] == "txn-9"
    assert kebab["reduced_payload"]["source_identifier"] == "42"
    assert camel["reduced_payload"]["source_identifier"] == "42"
    assert kebab["fine_conversion_value"] == 12
    assert camel["coarse_conversion_value"] == "medium"
    assert kebab["proof_level"] == "platform_verified"


def test_signature_status_is_honest_never_verified(adattributionkit_postback: dict):
    with_signature = reduce_postback(adattributionkit_postback)
    assert with_signature["signature_status"] == "unverified"

    without_signature = dict(adattributionkit_postback)
    del without_signature["attribution-signature"]
    assert reduce_postback(without_signature)["signature_status"] == "missing"

    # There is no code path that produces a "verified" status: no in-repo
    # Apple key verification utility exists, and we never fake one.
    assert not hasattr(module, "SIGNATURE_STATUS_VERIFIED")


def test_reduce_rejects_malformed_payloads(malformed_postback: dict):
    with pytest.raises(MalformedPostbackError):
        reduce_postback(malformed_postback)
    with pytest.raises(MalformedPostbackError):
        reduce_postback({})
    with pytest.raises(MalformedPostbackError):
        reduce_postback({"postback-id": "pb-1"})  # id but no campaign identity


# ── Route behaviour ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_stores_once_and_acknowledges_duplicates(
    adattributionkit_postback: dict, duplicate_postback: dict
):
    first = await ingest_apple_postback(
        ApplePostbackRequest(postback=adattributionkit_postback), TENANT
    )
    second = await ingest_apple_postback(
        ApplePostbackRequest(postback=duplicate_postback), TENANT
    )

    assert first["postback"]["duplicate"] is False
    assert second["postback"]["duplicate"] is True
    assert first["postback"]["apple_postback_id"] == second["postback"]["apple_postback_id"]
    assert len(module._LOCAL_APPLE_POSTBACKS) == 1

    stored = first["postback"]
    assert stored["environment"] == "sandbox"
    assert stored["coarse_conversion_value"] == "high"
    assert stored["fine_conversion_value"] == 42
    assert stored["proof_level"] == "platform_verified"
    assert stored["signature_status"] == "unverified"


@pytest.mark.asyncio
async def test_idempotency_is_tenant_scoped(adattributionkit_postback: dict):
    tenant_b = TenantContext(tenant_id="tenant-b", role=Role.SERVICE)
    a = await ingest_apple_postback(
        ApplePostbackRequest(postback=adattributionkit_postback), TENANT
    )
    b = await ingest_apple_postback(
        ApplePostbackRequest(postback=adattributionkit_postback), tenant_b
    )
    assert a["postback"]["duplicate"] is False
    assert b["postback"]["duplicate"] is False


@pytest.mark.asyncio
async def test_ingest_rejects_malformed_with_422(malformed_postback: dict):
    with pytest.raises(HTTPException) as exc:
        await ingest_apple_postback(
            ApplePostbackRequest(postback=malformed_postback), TENANT
        )
    assert exc.value.status_code == 422
    assert module._LOCAL_APPLE_POSTBACKS == {}


@pytest.mark.asyncio
async def test_rbac_requires_write_capable_credential():
    viewer = TenantContext(tenant_id="tenant-a", role=Role.VIEWER, permissions=[])
    with pytest.raises(HTTPException) as exc:
        await module._require_apple_postback_write(viewer)
    assert exc.value.status_code == 403

    permitted = TenantContext(
        tenant_id="tenant-a", role=Role.VIEWER, permissions=["apple_postbacks:write"]
    )
    assert await module._require_apple_postback_write(permitted) is permitted


def test_main_registers_apple_postbacks_router() -> None:
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[2]
    main_source = (backend_root / "main.py").read_text(encoding="utf-8")
    assert (
        "from services.attribution.apple_postbacks import router as apple_postbacks_router"
        in main_source
    )
    assert "app.include_router(apple_postbacks_router)" in main_source


def test_router_exposes_the_contract_path() -> None:
    route_methods = {
        (route.path, method)
        for route in module.router.routes
        for method in (route.methods or set())
    }
    assert ("/v1/attribution/apple-postbacks", "POST") in route_methods
