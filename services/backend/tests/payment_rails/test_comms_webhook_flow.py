"""Comms webhook authority seam — durable endpoint id → server-resolved tenant →
connector secret → signature verification → service ingest.

Proves the header-selected tenant is gone from the comms path (ADR-C11): tenant
ownership comes only from the ``whe_`` endpoint registry, and a genuine generic
Aether HMAC (or a native adapter scheme) verifies end to end through the wiring.
"""

from __future__ import annotations

import json
import os

import pytest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.connectors.service import ConnectorService  # noqa: E402
from services.integrations.providers.payment_rails.webhook_endpoints import (  # noqa: E402
    DOMAIN_COMMS,
    WebhookEndpointRegistry,
)
from services.integrations.webhook_policy import (  # noqa: E402
    verify_provider_webhook_signature,
)
from services.security.integration_security import sign_payload  # noqa: E402
from services.integrations.connectors.registry import get_connector  # noqa: E402

KLAVIYO_PAYLOAD = {
    "data": [
        {
            "id": "evt_comms_1",
            "type": "event",
            "attributes": {
                "metric": {"data": {"attributes": {"name": "Delivered Email"}}},
                "datetime": "2026-07-01T12:00:00Z",
                "event_properties": {"$email": "person@example.com", "$message": "msg_5"},
            },
        }
    ]
}


def _fresh() -> ConnectorService:
    reset_in_memory_stores()
    return ConnectorService()


@pytest.mark.asyncio
async def test_comms_webhook_server_resolved_tenant_and_ingest():
    svc = _fresh()
    reg = WebhookEndpointRegistry()

    # tenant configures klaviyo + mints a comms endpoint
    await svc.configure("tenantA", "klaviyo", enabled=True, credential="pk_abc123")
    ep = await reg.create("tenantA", "klaviyo", "sandbox",
                          created_by="admin", domain=DOMAIN_COMMS)

    # server-side resolution — no tenant header anywhere
    resolved = await reg.resolve(ep["endpoint_id"], "klaviyo", domain=DOMAIN_COMMS)
    assert resolved is not None
    tenant_id = resolved["tenant_id"]
    assert tenant_id == "tenantA"

    # connector secret resolves from the credential platform
    connector = get_connector("klaviyo")
    cfg_record = await svc.get(tenant_id, "klaviyo")
    from services.integrations.connectors.base import ConnectorConfig
    config = ConnectorConfig(**cfg_record)
    secret = await svc._resolve_secret(config)
    assert secret == "pk_abc123"

    # a genuine generic Aether HMAC verifies (replay window is checked against
    # real time, so sign with the current timestamp — a fixed past NOW is stale)
    raw_body = json.dumps(KLAVIYO_PAYLOAD).encode()
    headers = sign_payload(secret, raw_body)
    assert verify_provider_webhook_signature(
        connector, raw_body=raw_body,
        headers={**headers, "content-type": "application/json"},
        secret=secret, signature=headers["X-Aether-Signature"],
        timestamp=headers["X-Aether-Timestamp"],
    )

    # and a tampered body fails
    assert not verify_provider_webhook_signature(
        connector, raw_body=raw_body + b" ",
        headers={**headers, "content-type": "application/json"},
        secret=secret, signature=headers["X-Aether-Signature"],
        timestamp=headers["X-Aether-Timestamp"],
    )

    # ingest succeeds end to end (comms spine mocked — webhook authority is the
    # unit under test; the spine has its own tests)
    with patch(
        "services.comms.ingest.ingest_normalized_events",
        new=AsyncMock(return_value={"communications": 1, "catalog": 0, "identities": 0, "skipped": 0}),
    ):
        result = await svc.ingest_webhook(
            "klaviyo", tenant_id,
            raw_body=raw_body,
            signature=headers["X-Aether-Signature"],
            timestamp=headers["X-Aether-Timestamp"],
            secret=secret,
            headers={"content-type": "application/json"},
        )
    assert result["accepted"] is True
    assert result["events_ingested"] == 1


@pytest.mark.asyncio
async def test_comms_webhook_bad_signature_is_rejected_and_quarantined():
    svc = _fresh()
    reg = WebhookEndpointRegistry()

    await svc.configure("tenantA", "klaviyo", enabled=True, credential="pk_abc123")
    ep = await reg.create("tenantA", "klaviyo", "sandbox",
                          created_by="admin", domain=DOMAIN_COMMS)
    resolved = await reg.resolve(ep["endpoint_id"], "klaviyo", domain=DOMAIN_COMMS)
    tenant_id = resolved["tenant_id"]

    raw_body = json.dumps(KLAVIYO_PAYLOAD).encode()
    # signed with the wrong secret (current timestamp so only the secret differs)
    headers = sign_payload("pk_wrong", raw_body)

    from services.integrations.connectors.base import ConnectorConfig
    cfg_record = await svc.get(tenant_id, "klaviyo")
    config = ConnectorConfig(**cfg_record)
    secret = await svc._resolve_secret(config)

    result = await svc.ingest_webhook(
        "klaviyo", tenant_id,
        raw_body=raw_body,
        signature=headers["X-Aether-Signature"],
        timestamp=headers["X-Aether-Timestamp"],
        secret=secret,
        headers={"content-type": "application/json"},
    )
    assert result["accepted"] is False
    assert result["reason"] == "invalid signature"

    # denial is quarantined metadata-only (no payload body persisted)
    from services.integrations.webhook_quarantine import webhook_quarantine
    rows = await webhook_quarantine.find_many(filters={"tenant_id": tenant_id}, limit=10)
    assert any(r.get("reason_code") == "invalid_signature" for r in rows)
