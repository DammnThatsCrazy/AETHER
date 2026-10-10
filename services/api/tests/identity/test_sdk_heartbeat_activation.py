"""SDK heartbeat status is durable, tenant scoped, and metadata only."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from repositories.sdk_heartbeat_status import (  # noqa: E402
    get_sdk_heartbeat_status_repository,
    reset_sdk_heartbeat_status_memory,
)
from governance.consent.authority import ConsentReceiptRepository  # noqa: E402
from identity.identity.repository import IdentityResolutionRepository  # noqa: E402
from ingestion.sdk import lifecycle_routes  # noqa: E402


TENANT = "tenant_sdk_heartbeat"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_sdk_heartbeat_status_memory()


class _Cache:
    async def incr(self, _key, _amount=1):
        return 1


def _request(*, tenant_id=TENANT, sites=None):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sdk/heartbeat",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=tenant_id, site_ids=sites)},
    })


async def _grant(anonymous_id):
    await ConsentReceiptRepository().record(
        receipt_id=f"heartbeat-receipt-{anonymous_id}",
        tenant_id=TENANT,
        purpose="analytics",
        state="granted",
        anonymous_id=anonymous_id,
        mode="opt_in",
        metadata={"scope": "identity"},
    )


@pytest.mark.asyncio
async def test_heartbeat_persists_app_sdk_liveness_without_identity_consent_or_identifiers():
    response = await lifecycle_routes.sdk_heartbeat(
        lifecycle_routes.HeartbeatRequest(
            sdk_name="aether-web",
            sdk_version="2.4.1",
            tenant_app_key="storefront",
            anonymous_id="unconsented-anonymous",
            installation_id="installation-secret",
            device_id="device-secret",
        ),
        _request(sites=["storefront"]),
        cache=_Cache(),
    )

    rows = await get_sdk_heartbeat_status_repository().list_for_tenant(TENANT)
    assert response.received is True
    assert response.source_identity_id is None
    assert len(rows) == 1
    assert rows[0]["sdk_name"] == "aether-web"
    assert rows[0]["tenant_app_key"] == "storefront"
    assert rows[0]["sdk_version"] == "2.4.1"
    assert rows[0]["heartbeat_count"] == 1
    assert "unconsented-anonymous" not in repr(rows)
    assert "installation-secret" not in repr(rows)
    assert "device-secret" not in repr(rows)
    assert await IdentityResolutionRepository()._source_identities.find_many(
        filters={"tenant_id": TENANT}
    ) == []


@pytest.mark.asyncio
async def test_heartbeat_identity_write_requires_current_server_receipt_and_status_updates():
    await _grant("consented-anonymous")
    first = await lifecycle_routes.sdk_heartbeat(
        lifecycle_routes.HeartbeatRequest(
            sdk_name="aether-ios",
            sdk_version="1.3.0",
            tenant_app_key="mobile-app",
            anonymous_id="consented-anonymous",
            installation_id="install-1",
        ),
        _request(sites=["mobile-app"]),
        cache=_Cache(),
    )
    second = await lifecycle_routes.sdk_heartbeat(
        lifecycle_routes.HeartbeatRequest(
            sdk_name="aether-ios",
            sdk_version="1.3.1",
            tenant_app_key="mobile-app",
            anonymous_id="consented-anonymous",
            installation_id="install-1",
        ),
        _request(sites=["mobile-app"]),
        cache=_Cache(),
    )

    rows = await get_sdk_heartbeat_status_repository().list_for_tenant(TENANT)
    assert first.source_identity_id
    assert second.source_identity_id == first.source_identity_id
    assert rows[0]["heartbeat_count"] == 2
    assert rows[0]["sdk_version"] == "1.3.1"
    assert rows[0]["last_seen_at"] >= rows[0]["first_seen_at"]
    source = await IdentityResolutionRepository().get_source_identity(first.source_identity_id)
    assert source["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_heartbeat_rejects_app_outside_authenticated_sdk_scope():
    with pytest.raises(HTTPException) as error:
        await lifecycle_routes.sdk_heartbeat(
            lifecycle_routes.HeartbeatRequest(
                sdk_name="aether-web",
                sdk_version="1.0.0",
                tenant_app_key="attacker-site",
                anonymous_id="anon",
            ),
            _request(sites=["trusted-site"]),
            cache=_Cache(),
        )

    assert error.value.status_code == 403
    assert await get_sdk_heartbeat_status_repository().list_for_tenant(TENANT) == []
