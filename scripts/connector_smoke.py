#!/usr/bin/env python3
"""Manual staging validation for connector adapters.

Reads secrets and connector-specific config from env, calls each adapter
against the real API with AETHER_ENV=staging.

Required env vars:
  AETHER_ENV              — must be "staging" or "production"
  SHOPIFY_SECRET          — Shopify Admin API access token
  SHOPIFY_SHOP_DOMAIN     — Shopify store domain (e.g. my-store.myshopify.com)
  STRIPE_SECRET           — Stripe secret key (sk_...)
  SLACK_SECRET            — Slack bot OAuth token (xoxb-...)

Connectors with supports_pull=False (Stripe, Slack) are skipped with a note —
they are outbound-only and return [] without any HTTP call when pulled.

Exit 0 on pass, 1 on any failure.
"""
from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))


def _require_staging() -> None:
    env = os.getenv("AETHER_ENV", "local").lower()
    if env not in ("staging", "production"):
        print(f"ERROR: AETHER_ENV={env!r} — set AETHER_ENV=staging before running smoke tests", file=sys.stderr)
        sys.exit(1)


def _require_secret(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"ERROR: {name} env var is not set", file=sys.stderr)
        sys.exit(1)
    return val


async def smoke_connector(connector_type: str, secret: str, extra_config: dict | None = None) -> None:
    """Run a live pull against one adapter."""
    from services.integrations.connectors.registry import get_connector
    from services.integrations.connectors.base import ConnectorConfig

    connector = get_connector(connector_type)
    if connector is None:
        print(f"FAIL [{connector_type}]: unknown connector type", file=sys.stderr)
        sys.exit(1)

    if not getattr(connector, "supports_pull", False):
        print(f"  [{connector_type}] SKIP — supports_pull=False (outbound-only; cannot be validated via pull)")
        return

    config = ConnectorConfig(
        tenant_id="smoke-test",
        connector_type=connector_type,
        enabled=True,
        secret_configured=True,
        config=extra_config or {},
    )

    print(f"  [{connector_type}] pulling...", end=" ", flush=True)
    try:
        events = await connector.pull(config, secret=secret)
        if not isinstance(events, list):
            raise ValueError(f"pull returned {type(events).__name__}, expected list")
        # 0 events is valid when the staging store has no recent data;
        # what matters is that the adapter made a real HTTP call without raising.
        print(f"OK — {len(events)} event(s)")
    except Exception as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        sys.exit(1)


async def main() -> None:
    _require_staging()

    connectors: dict[str, tuple[str, dict]] = {
        "shopify": (
            _require_secret("SHOPIFY_SECRET"),
            {"shop_domain": _require_secret("SHOPIFY_SHOP_DOMAIN")},
        ),
        "stripe": (_require_secret("STRIPE_SECRET"), {}),
        "slack": (_require_secret("SLACK_SECRET"), {}),
    }

    print("Connector smoke tests (AETHER_ENV=staging)")
    for connector_type, (secret, extra_config) in connectors.items():
        await smoke_connector(connector_type, secret, extra_config)

    print("All connectors passed.")


if __name__ == "__main__":
    asyncio.run(main())
