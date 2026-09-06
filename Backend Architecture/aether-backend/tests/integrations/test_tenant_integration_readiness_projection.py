"""Tenant-contextual integration readiness — honesty-invariant tests (WS-4).

The joined readiness graph (services/readiness_graph/tenant_integration_readiness*)
combines tenant connection record facts + the manifest's catalog readiness into
an evidence-derived tenant_state. These tests pin the honesty law:

* ``readiness`` is ALWAYS the manifest catalog baseline — tenant connection
  evidence can never raise it (Connected ≠ Ready; nothing may read live/ready
  without proof).
* ``connected`` is a record fact, never a readiness claim.
* every ``tenant_state`` is derived from concrete evidence; ``ready`` requires
  proof on BOTH the provider (catalog sandbox-validated+) and the connection
  (healthy) axes.
"""

from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

from shared.certification.readiness import CredentialReadiness, readiness_rank
from shared.integration_contracts.catalog import (
    ALL_MANIFESTS,
    ad_manifest_by_family,
    manifest_by_family,
)
from shared.integration_contracts.lifecycle import (
    ConnectionState,
    from_connector_sync_status,
)
from shared.integration_contracts.manifest import ManifestReadiness
from services.readiness_graph.tenant_integration_readiness import (
    REASON_CREDENTIAL_MISSING,
    REASON_PROVIDER_OFF_RAMP,
    REASON_SYNC_DEGRADED,
    REASON_SYNC_FAILED,
    READY_MIN_RANK,
    TenantIntegrationState,
    connection_state_for,
    project_tenant_integration,
    tenant_state_for,
)
from services.readiness_graph.tenant_integration_readiness_routes import (
    build_tenant_readiness_items,
)

_STATE_VALUES = {s.value for s in TenantIntegrationState}
_VISIBLE_FAMILIES = {
    m.provider_family
    for m in ALL_MANIFESTS
    if m.availability.environments.any_enabled()
}
#: One readiness item is emitted per *visible manifest* (a family can carry two
#: enabled manifests), so the coverage count is the manifest list, not the set.
_VISIBLE_MANIFEST_COUNT = sum(
    1 for m in ALL_MANIFESTS if m.availability.environments.any_enabled()
)


def _row(*, connector_type="shopify", enabled=True, secret_configured=True,
         sync_status="healthy", last_synced_at=None, error_count=0,
         last_error_at=None) -> dict:
    return {
        "connector_type": connector_type,
        "name": connector_type.title(),
        "enabled": enabled,
        "secret_configured": secret_configured,
        "sync_status": sync_status,
        "last_synced_at": last_synced_at,
        "error_count": error_count,
        "last_error_at": last_error_at,
    }


# ── Connected is a record fact; readiness is the manifest catalog baseline ──


def test_healthy_connection_never_raises_catalog_readiness() -> None:
    """A healthy tenant sync cannot lift a credential_waiting adapter to live."""
    shopify = manifest_by_family["shopify"]
    assert shopify.readiness.state == CredentialReadiness.CREDENTIAL_WAITING
    item = project_tenant_integration(shopify, _row(sync_status="healthy"))
    assert item["tenant_state"] == TenantIntegrationState.CONNECTED.value
    # Provider truth is unchanged by the tenant's healthy connection.
    assert item["readiness"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value
    assert item["readiness"]["rank"] == readiness_rank(
        CredentialReadiness.CREDENTIAL_WAITING
    )
    assert item["readiness"]["level"] == 3
    assert item["attention_reasons"] == []
    # The record facts are present and honest.
    conn = item["connection"]
    assert conn["connected"] is True
    assert conn["state"] == ConnectionState.CONNECTED.value
    assert conn["sync_status"] == "healthy"


def test_connected_is_record_fact_for_each_leg() -> None:
    """enabled OR secret_configured OR ever-synced -> connected record fact."""
    meta = ad_manifest_by_family["meta_ads"]  # credential-bearing ad manifest
    legs = [
        # enabled, credential not yet configured -> fact yes, but needs attention
        # (a credential-bearing provider with an enabled, credential-less
        # connection cannot run and must not read green).
        (_row(enabled=True, secret_configured=False, sync_status="never_synced"),
         TenantIntegrationState.NEEDS_ATTENTION),
        # credential configured, awaiting first sync -> connected fact.
        (_row(enabled=False, secret_configured=True, sync_status="never_synced"),
         TenantIntegrationState.CONNECTED),
        # ever synced -> connected fact.
        (_row(enabled=False, secret_configured=False, sync_status="healthy",
              last_synced_at="2026-09-01T00:00:00Z"),
         TenantIntegrationState.CONNECTED),
    ]
    for row, expected_state in legs:
        item = project_tenant_integration(meta, row)
        assert item["connection"]["connected"] is True
        assert item["tenant_state"] == expected_state.value
        # Even with a record fact, catalog readiness stays the manifest's token.
        assert item["readiness"]["state"] == meta.readiness.state.value


def test_unconfigured_integration_is_available_with_catalog_baseline() -> None:
    meta = ad_manifest_by_family["meta_ads"]
    item = project_tenant_integration(meta, None)
    assert item["tenant_state"] == TenantIntegrationState.AVAILABLE.value
    assert item["connection"]["configured"] is False
    assert item["connection"]["connected"] is False
    # Readiness is the manifest's catalog baseline — a connectable fact.
    assert item["readiness"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value


def test_residual_inactive_record_is_not_connected() -> None:
    """A stored row with no connection fact reads available, never connected."""
    slack = manifest_by_family["slack"]
    row = _row(enabled=False, secret_configured=False, sync_status="never_synced")
    item = project_tenant_integration(slack, row)
    assert item["tenant_state"] == TenantIntegrationState.AVAILABLE.value
    assert item["connection"]["configured"] is True
    assert item["connection"]["connected"] is False


def test_tenant_state_vocabulary_is_not_a_readiness_token() -> None:
    """The emitted state set is the connection/attention vocabulary only."""
    for row in [None, _row(), _row(sync_status="failed")]:
        state, _ = tenant_state_for(row, manifest_by_family["shopify"])
        assert state.value in _STATE_VALUES
    # No emitted state may look like a CredentialReadiness ladder token.
    readiness_words = {r.value for r in CredentialReadiness}
    assert _STATE_VALUES.isdisjoint(readiness_words)


# ── needs_attention is derived from concrete evidence ───────────────────────


def test_failed_sync_is_needs_attention_with_reason() -> None:
    shopify = manifest_by_family["shopify"]
    row = _row(sync_status="failed", error_count=3, last_error_at="2026-09-04T00:00:00Z")
    item = project_tenant_integration(shopify, row)
    assert item["tenant_state"] == TenantIntegrationState.NEEDS_ATTENTION.value
    assert REASON_SYNC_FAILED in item["attention_reasons"]
    assert item["connection"]["state"] == ConnectionState.SYNC_FAILED.value
    # Connection evidence may only lower effective truth; catalog stays put.
    assert item["readiness"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value


def test_degraded_sync_is_needs_attention_with_reason() -> None:
    shopify = manifest_by_family["shopify"]
    item = project_tenant_integration(shopify, _row(sync_status="degraded"))
    assert item["tenant_state"] == TenantIntegrationState.NEEDS_ATTENTION.value
    assert REASON_SYNC_DEGRADED in item["attention_reasons"]


def test_enabled_credential_bearing_connection_without_credential_is_needs_attention() -> None:
    """'Readiness is missing a credential': enabled + no secret on a
    credential-bearing provider cannot run and must not read green."""
    meta = ad_manifest_by_family["meta_ads"]
    assert meta.authentication.type == "api_key"
    row = _row(enabled=True, secret_configured=False, sync_status="never_synced")
    item = project_tenant_integration(meta, row)
    assert item["tenant_state"] == TenantIntegrationState.NEEDS_ATTENTION.value
    assert REASON_CREDENTIAL_MISSING in item["attention_reasons"]


def test_provider_off_ramp_manifest_is_needs_attention() -> None:
    """A provider pulled to an off-ramp makes an existing connection actionable."""
    shopify = manifest_by_family["shopify"]
    off_ramp = shopify.model_copy(
        update={
            "readiness": ManifestReadiness(
                state=CredentialReadiness.SUSPENDED,
                level=1,
            )
        }
    )
    state, reasons = tenant_state_for(_row(sync_status="healthy"), off_ramp)
    assert state == TenantIntegrationState.NEEDS_ATTENTION
    assert REASON_PROVIDER_OFF_RAMP in reasons


def test_disabled_connection_is_disabled_not_attention() -> None:
    """A tenant-turned-off connection is its own state, not a false alarm."""
    shopify = manifest_by_family["shopify"]
    row = _row(enabled=False, secret_configured=True, sync_status="disabled")
    item = project_tenant_integration(shopify, row)
    assert item["tenant_state"] == TenantIntegrationState.CONNECTION_DISABLED.value
    assert item["attention_reasons"] == []
    assert item["connection"]["state"] == ConnectionState.DISABLED.value


# ── ready requires proof on BOTH axes ───────────────────────────────────────


def test_ready_requires_provider_sandbox_validated_and_healthy_connection() -> None:
    sandbox = manifest_by_family["shopify"].model_copy(
        update={
            "readiness": ManifestReadiness(
                state=CredentialReadiness.SANDBOX_VALIDATED, level=4
            )
        }
    )
    assert readiness_rank(sandbox.readiness.state) >= READY_MIN_RANK
    state, reasons = tenant_state_for(_row(sync_status="healthy"), sandbox)
    assert state == TenantIntegrationState.READY
    assert reasons == []
    # But the SAME provider with a failing connection is NOT ready.
    state_failed, reasons_failed = tenant_state_for(
        _row(sync_status="failed"), sandbox
    )
    assert state_failed == TenantIntegrationState.NEEDS_ATTENTION
    assert REASON_SYNC_FAILED in reasons_failed


def test_credential_waiting_provider_can_never_emit_ready() -> None:
    """The honest posture: nothing below sandbox-validated may read ready."""
    for family in _VISIBLE_FAMILIES:
        manifest = manifest_by_family.get(family)
        if manifest is None:
            continue  # only BYOD connector manifests share connector_state rows
        assert readiness_rank(manifest.readiness.state) < READY_MIN_RANK
        state, _ = tenant_state_for(_row(sync_status="healthy"), manifest)
        assert state != TenantIntegrationState.READY


def test_no_manifest_means_no_provider_readiness_claim() -> None:
    """Without a certified manifest the projection claims no readiness."""
    item = project_tenant_integration(None, _row(enabled=True, secret_configured=True))
    assert item["readiness"] is None
    # Connection facts are still reported.
    assert item["connection"]["connected"] is True
    assert item["tenant_state"] == TenantIntegrationState.CONNECTED.value


# ── Connection state projection stays on the lifecycle machine ─────────────


def test_connection_state_for_uses_canonical_lifecycle_mapping() -> None:
    for sync in ("never_synced", "syncing", "healthy", "degraded", "failed",
                 "disabled"):
        assert connection_state_for(_row(sync_status=sync)) == (
            from_connector_sync_status(sync)
        )
    assert connection_state_for(_row(enabled=False, secret_configured=False,
                                     sync_status="never_synced")) == (
        ConnectionState.AVAILABLE
    )


# ── Whole-graph assembly (pure) ─────────────────────────────────────────────


def test_build_items_covers_catalog_and_marks_unconfigured_available() -> None:
    items = build_tenant_readiness_items("tenant-a", {})
    by_family = {i["family"]: i for i in items}
    assert set(by_family) == _VISIBLE_FAMILIES
    for item in items:
        assert item["connection"]["configured"] is False
        assert item["tenant_state"] == TenantIntegrationState.AVAILABLE.value
        # Every connectable manifest carries its honest catalog baseline.
        assert item["readiness"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value
        assert item["readiness"]["rank"] == readiness_rank(
            CredentialReadiness(item["readiness"]["state"])
        )


def test_build_items_joins_tenant_rows_and_flags_provider_off_ramps() -> None:
    shopify = manifest_by_family["shopify"]
    healthy = _row(connector_type="shopify", sync_status="healthy")
    items = build_tenant_readiness_items("tenant-a", {"shopify": healthy})
    by_family = {i["family"]: i for i in items}
    assert by_family["shopify"]["tenant_state"] == (
        TenantIntegrationState.CONNECTED.value
    )
    # Configured-but-no-longer-visible families still surface (honest leftovers).
    off_ramp_family = next(
        (fam for fam in manifest_by_family
         if fam not in _VISIBLE_FAMILIES),
        None,
    )
    if off_ramp_family is not None:
        row = _row(connector_type=off_ramp_family, sync_status="healthy")
        items2 = build_tenant_readiness_items("tenant-a", {off_ramp_family: row})
        fam2 = {i["family"]: i for i in items2}
        assert fam2[off_ramp_family]["connection"]["connected"] is True


# ── Route-level: the joined projection is served honestly ───────────────────
import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from repositories.repos import reset_in_memory_stores
from shared.common.common import AetherError
from services.integrations.connectors.service import connector_service

_TENANT_A = "tenantA"
_TENANT_B = "tenantB"


class _FakeTenant:
    tenant_id = _TENANT_A
    user_id = "user_test"

    @staticmethod
    def require_permission(_perm: str) -> None:
        return None


def _make_app() -> FastAPI:
    from services.readiness_graph.tenant_integration_readiness_routes import (
        router as tenant_integration_readiness_router,
    )

    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _aether_errors(request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = _FakeTenant()
        return await call_next(request)

    app.include_router(tenant_integration_readiness_router)
    return app


@pytest.fixture()
def readiness_client():
    reset_in_memory_stores()
    with TestClient(_make_app()) as client:
        yield client
    reset_in_memory_stores()


def _seed_connector(connector_type: str, tenant_id: str = _TENANT_A, **over) -> None:
    """Write a ConnectorConfig-shaped record fact for a tenant into the shared
    in-memory backing store (AETHER_ENV=local)."""
    row = _row(connector_type=connector_type, **over)
    row["tenant_id"] = tenant_id
    asyncio.run(
        connector_service.repo.insert(f"{tenant_id}:{connector_type}", row)
    )


def test_route_serves_every_connectable_manifest_as_available(readiness_client) -> None:
    client = readiness_client
    resp = client.get("/v1/tenant/integration-readiness")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tenant_id"] == _TENANT_A
    assert data["count"] == _VISIBLE_MANIFEST_COUNT
    assert data["states_present"] == [TenantIntegrationState.AVAILABLE.value]
    by_family = {i["family"]: i for i in data["items"]}
    assert set(by_family) == _VISIBLE_FAMILIES
    for item in data["items"]:
        assert item["tenant_state"] == TenantIntegrationState.AVAILABLE.value
        assert item["connection"]["configured"] is False
        # The honest catalog baseline is served for every connectable provider.
        assert item["readiness"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value


def test_route_reports_connected_record_fact_without_raising_catalog(readiness_client) -> None:
    _seed_connector("shopify", sync_status="healthy", last_synced_at="2026-09-01T00:00:00Z")
    client = readiness_client
    resp = client.get("/v1/tenant/integration-readiness")
    data = resp.json()["data"]
    assert data["count"] == _VISIBLE_MANIFEST_COUNT  # coverage stays whole
    assert "connected" in data["states_present"]
    shopify = next(i for i in data["items"] if i["family"] == "shopify")
    assert shopify["tenant_state"] == TenantIntegrationState.CONNECTED.value
    assert shopify["connection"]["connected"] is True
    assert shopify["connection"]["sync_status"] == "healthy"
    # Connection evidence may not lift the manifest's credential_waiting token.
    assert shopify["readiness"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value
    assert shopify["readiness"]["rank"] == 20


def test_route_state_filter_returns_only_matching_attention_items(readiness_client) -> None:
    _seed_connector("shopify", sync_status="failed", error_count=3)
    client = readiness_client
    attention = client.get(
        "/v1/tenant/integration-readiness", params={"state": "needs_attention"}
    )
    available = client.get(
        "/v1/tenant/integration-readiness", params={"state": "available"}
    )
    att_data = attention.json()["data"]
    assert att_data["count"] == 1
    assert att_data["items"][0]["family"] == "shopify"
    assert REASON_SYNC_FAILED in att_data["items"][0]["attention_reasons"]
    avail_data = available.json()["data"]
    assert "shopify" not in {i["family"] for i in avail_data["items"]}


def test_route_readiness_is_scoped_to_the_calling_tenant(readiness_client) -> None:
    # A different tenant's healthy shopify record must not make tenantA's
    # shopify read connected — readiness is never asserted from a parallel token.
    _seed_connector("shopify", tenant_id=_TENANT_B, sync_status="healthy")
    client = readiness_client
    resp = client.get("/v1/tenant/integration-readiness")
    data = resp.json()["data"]
    shopify = next(i for i in data["items"] if i["family"] == "shopify")
    assert data["tenant_id"] == _TENANT_A
    assert shopify["tenant_state"] == TenantIntegrationState.AVAILABLE.value
    assert shopify["connection"]["connected"] is False


def test_route_experience_category_filter_restricts_coverage(readiness_client) -> None:
    from shared.integration_contracts.experience import experience_category_for

    shopify_exp = experience_category_for(manifest_by_family["shopify"])
    assert shopify_exp is not None
    client = readiness_client
    resp = client.get(
        "/v1/tenant/integration-readiness",
        params={"experience_category": shopify_exp.value},
    )
    data = resp.json()["data"]
    assert data["items"]
    for item in data["items"]:
        assert item["experience_category"] == shopify_exp.value


def test_route_unknown_state_value_is_rejected_not_silently_green(readiness_client) -> None:
    client = readiness_client
    resp = client.get(
        "/v1/tenant/integration-readiness", params={"state": "partner_live"}
    )
    data = resp.json()["data"]
    assert data["count"] == 0
    assert "error" in data  # an unrecognized state never fabricates a green item
