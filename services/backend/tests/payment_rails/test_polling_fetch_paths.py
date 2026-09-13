"""Provider-truth pull-path hardening — ``_fetch_poll_records`` error surface
and the webhook-only no-op (polling-fetch hardening gap).

WHAT THIS COVERS / WHY IT WAS NEEDED
------------------------------------
``tests/payment_rails/test_polling.py`` already drives the happy pull paths
(cursor / time-window pagination, auth injection, redaction, cursor recovery)
plus the ``timeout``, ``rate_limited`` (429-retry) and ``auth_error`` (401)
classifications for the three pull-capable adapters (Coinbase / MoonPay /
Bridge). This module closes the remaining GENUINE holes in the pull surface so
that *every* branch of the shared ``PaymentRailAdapter._request_json``
classifier and every pull-capable adapter's ``_fetch_poll_records`` is exercised
through the injected ``httpx.MockTransport`` — with NO live network:

  1. ``server_error`` (HTTP 5xx exhausting retries) degrades provider poll
     health and returns the records gathered so far — the sweep NEVER raises.
  2. ``client_error`` (a non-auth 4xx) is classified without retry, again
     returning partial records.
  3. ``bad_response`` (HTTP 200 with an unparseable body) is classified as such.
  4. ``not_configured`` short-circuits the pull for MoonPay and Bridge (no
     credential → zero HTTP requests, health ``not_configured``) — the Coinbase
     case is in ``test_polling.py``; this fills the other two pull adapters.
  5. The webhook-only providers (Privy, Stripe) correctly fall through to the
     base ``_fetch_poll_records`` default: they perform NO network IO and set
     poll health to ``webhook_only`` (a supported terminal capability, not an
     unfinished adapter). This CONFIRMS they are not accidentally on a broken
     pull path and that only Coinbase / MoonPay / Bridge override the fetch.

DELIVERY-INTEGRITY GUARANTEE PROTECTED
--------------------------------------
A degraded provider poll must never crash the supervised sync sweep or fabricate
a success: partial truth is returned, provider health is recorded for alerting,
and a webhook-only provider is a clean no-op. This keeps the "one canonical
event per real observation" guarantee intact — a poll failure can neither drop a
real record already fetched nor invent one.

NO PRODUCT FIX WAS REQUIRED for this gap: Coinbase / MoonPay / Bridge already
override ``_fetch_poll_records`` with correct pagination + error classification,
and Privy / Stripe already inherit the webhook-only base default. This module
proves that and pins it against regression.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional

import httpx
import pytest

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_providers as mp  # noqa: E402

from services.integrations.providers.payment_rails.base import (  # noqa: E402
    POLL_HEALTH_BAD_RESPONSE,
    POLL_HEALTH_CLIENT_ERROR,
    POLL_HEALTH_NOT_CONFIGURED,
    POLL_HEALTH_SERVER_ERROR,
    get_payment_rails_vault,
)
from services.integrations.providers.payment_rails.bridge import BridgeAdapter  # noqa: E402
from services.integrations.providers.payment_rails.coinbase import CoinbaseAdapter  # noqa: E402
from services.integrations.providers.payment_rails.moonpay import MoonPayAdapter  # noqa: E402
from services.integrations.providers.payment_rails.privy import PrivyAdapter  # noqa: E402
from services.integrations.providers.payment_rails.stripe_onramp import (  # noqa: E402
    StripeOnrampAdapter,
)

pytestmark = pytest.mark.asyncio


async def _noop(_seconds):  # deterministic: never actually sleep between retries
    return None


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


async def _configure(adapter, tenant_id: str, secret: str) -> None:
    await get_payment_rails_vault().store_key(
        tenant_id, adapter.vault_provider_name, "payment", secret
    )


def _recording_transport(
    responder: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A minimal recording ``MockTransport`` for bespoke status-code scenarios.

    ``mock_providers`` only injects 429/timeout faults; the classifier branches
    below (5xx / 4xx / bad JSON) need arbitrary responses, so this records every
    request and delegates the response to ``responder``. No socket is opened —
    ``httpx.MockTransport`` routes every request to the in-process handler.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder(request)

    return httpx.MockTransport(handler), seen


# ── error classification through the shared _request_json classifier ──────────


class TestPullErrorClassification:
    """Every remaining ``POLL_HEALTH_*`` classification branch, driven through
    Coinbase's cursor pull so the partial-records-then-degrade behaviour is
    observable (page 1 succeeds, page 2 faults)."""

    async def test_server_error_degrades_and_returns_partial_records(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        t1 = mp.coinbase_tx("cb1", "ONRAMP_TRANSACTION_STATUS_SUCCESS")

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("page_key") == "c2":
                return httpx.Response(503, json={"error": "unavailable"}, request=request)
            return httpx.Response(
                200, json={"transactions": [t1], "next_page_key": "c2"}, request=request
            )

        transport, seen = _recording_transport(responder)
        # max_retries=0 so the 5xx raises immediately after one attempt (no waits).
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop, max_retries=0)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)

        # Page 1's record survived; the 5xx on page 2 degraded health WITHOUT raising.
        assert [r["transaction_id"] for r in records] == ["cb1"]
        assert poll_state["health"] == POLL_HEALTH_SERVER_ERROR
        assert len(seen) == 2  # page 1 (200) + page 2 (503, no retry)

    async def test_client_error_is_classified_without_retry(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        t1 = mp.coinbase_tx("cb1", "ONRAMP_TRANSACTION_STATUS_SUCCESS")

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("page_key") == "c2":
                # 404 is a non-auth 4xx → client_error, never retried.
                return httpx.Response(404, json={"error": "not_found"}, request=request)
            return httpx.Response(
                200, json={"transactions": [t1], "next_page_key": "c2"}, request=request
            )

        transport, seen = _recording_transport(responder)
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop, max_retries=3)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)

        assert [r["transaction_id"] for r in records] == ["cb1"]  # partial truth kept
        assert poll_state["health"] == POLL_HEALTH_CLIENT_ERROR
        # 4xx is terminal (not retried) even though max_retries=3.
        assert len(seen) == 2

    async def test_unparseable_body_is_bad_response(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        t1 = mp.coinbase_tx("cb1", "ONRAMP_TRANSACTION_STATUS_SUCCESS")

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("page_key") == "c2":
                # HTTP 200 but the body is not JSON → response.json() raises.
                return httpx.Response(200, content=b"<html>not json</html>", request=request)
            return httpx.Response(
                200, json={"transactions": [t1], "next_page_key": "c2"}, request=request
            )

        transport, _ = _recording_transport(responder)
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop, max_retries=0)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)

        assert [r["transaction_id"] for r in records] == ["cb1"]
        assert poll_state["health"] == POLL_HEALTH_BAD_RESPONSE


# ── not_configured short-circuit for the remaining pull adapters ──────────────


class TestNotConfiguredShortCircuit:
    """A pull adapter with no credential must classify ``not_configured`` and
    make ZERO HTTP requests. (Coinbase is covered in ``test_polling.py``; this
    fills MoonPay and Bridge so all three pull adapters are pinned.)"""

    async def test_moonpay_not_configured_makes_no_request(self):
        transport, server = mp.moonpay_transport(secret="x", windows={None: []})
        adapter = MoonPayAdapter(http_transport=transport, sleeper=_noop)
        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(_tenant(), poll_state=poll_state)
        assert records == []
        assert poll_state["health"] == POLL_HEALTH_NOT_CONFIGURED
        assert server.requests == []  # never touched the (mock) network

    async def test_bridge_not_configured_makes_no_request(self):
        transport, server = mp.bridge_transport(secret="x", pages={None: []})
        adapter = BridgeAdapter(http_transport=transport, sleeper=_noop)
        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(
            _tenant(), poll_state=poll_state, customer_id="cust1"
        )
        assert records == []
        assert poll_state["health"] == POLL_HEALTH_NOT_CONFIGURED
        assert server.requests == []


# ── webhook-only providers correctly no-op through the base default ───────────


class TestWebhookOnlyNoOp:
    """Privy and Stripe expose no pull API. They must inherit the base
    ``_fetch_poll_records`` default: no network IO, poll health ``webhook_only``,
    and NO ``build_request`` (so certification request/auth checks correctly
    skip). This confirms only the three pull adapters override the fetch path."""

    @pytest.mark.parametrize("adapter_cls", [PrivyAdapter, StripeOnrampAdapter])
    async def test_fetch_is_a_webhook_only_no_op(self, adapter_cls):
        adapter = adapter_cls()
        assert adapter.polling_supported is False
        assert adapter.webhook_only is True
        # Webhook-only providers never construct a provider request.
        assert not hasattr(adapter, "build_request")

        poll_state: dict = {}
        records = await adapter._fetch_poll_records(_tenant(), poll_state=poll_state)
        assert records == []
        assert poll_state["health"] == "webhook_only"

    @pytest.mark.parametrize("adapter_cls", [PrivyAdapter, StripeOnrampAdapter])
    async def test_status_sync_records_none_is_empty_for_webhook_only(self, adapter_cls):
        # ``status_sync`` with no supplied records short-circuits for a
        # webhook-only provider (polling_supported is False) — a no-op, never a
        # fabricated poll result.
        adapter = adapter_cls()
        events = await adapter.status_sync(_tenant(), environment="sandbox")
        assert events == []
