"""Durable connector webhook endpoint registry.

The public connector webhook URL is
``/v1/integrations/webhooks/connectors/{connector_type}/{endpoint_id}``. The
``endpoint_id`` is high-entropy, non-sequential, durable, revocable and bound
to exactly one (tenant, connector, environment) — resolution happens
server-side, replacing the untrusted ``X-Aether-Tenant-ID`` header the legacy
route accepted. The id alone is not authentication; the provider or Aether
HMAC signature is still verified downstream.

Reuses the payment-rails ``WebhookEndpointRegistry`` semantics over a
connector-scoped table and id prefix.
"""

from __future__ import annotations

from services.integrations.providers.payment_rails.webhook_endpoints import (
    WebhookEndpointRegistry,
)

CONNECTOR_ENDPOINT_TABLE = "connector_webhook_endpoints"
_ID_PREFIX = "cwe_"
_PATH_TEMPLATE = "/v1/integrations/webhooks/connectors/{provider}/{endpoint_id}"


# Module singleton — durable state lives in the DB.
connector_webhook_endpoint_registry = WebhookEndpointRegistry(
    table=CONNECTOR_ENDPOINT_TABLE,
    id_prefix=_ID_PREFIX,
    path_template=_PATH_TEMPLATE,
)


__all__ = [
    "connector_webhook_endpoint_registry",
    "CONNECTOR_ENDPOINT_TABLE",
]
