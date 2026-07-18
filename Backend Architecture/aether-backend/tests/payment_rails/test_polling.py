"""Provider-truth pull tests for Coinbase / MoonPay / Bridge.

Drives each adapter's ``_fetch_poll_records`` against an in-process mock HTTP
server (``httpx.MockTransport`` injected via ``http_transport=``) — NO live
network. Proves: authenticated request construction, credential injection,
pagination, cursor recovery, secret redaction before storage, rate-limit +
retry, timeout classification, auth-failure degradation, not-configured
short-circuit, and the authenticated live connection test.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_providers as mp  # noqa: E402

from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
)
from services.integrations.providers.payment_rails.bridge import BridgeAdapter  # noqa: E402
from services.integrations.providers.payment_rails.coinbase import CoinbaseAdapter  # noqa: E402
from services.integrations.providers.payment_rails.moonpay import MoonPayAdapter  # noqa: E402

pytestmark = pytest.mark.asyncio


async def _noop(_seconds):  # deterministic: never actually sleep during retries
    return None


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


async def _configure(adapter, tenant_id: str, secret: str) -> None:
    await get_payment_rails_vault().store_key(
        tenant_id, adapter.vault_provider_name, "payment", secret
    )


# ── Coinbase: cursor pagination ──────────────────────────────────────────────


class TestCoinbasePull:
    async def test_pagination_auth_and_redaction(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        t1 = mp.coinbase_tx("cb1", "ONRAMP_TRANSACTION_STATUS_STARTED")
        t2 = mp.coinbase_tx("cb2", "ONRAMP_TRANSACTION_STATUS_SUCCESS")
        t3 = mp.coinbase_tx("cb3", "ONRAMP_TRANSACTION_STATUS_SUCCESS")
        transport, server = mp.coinbase_transport(
            secret=secret, pages={None: ([t1, t2], "c2"), "c2": ([t3], None)}
        )
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(
            tenant_id, poll_state=poll_state, partner_user_ref="user-42"
        )

        assert [r["transaction_id"] for r in records] == ["cb1", "cb2", "cb3"]
        assert poll_state["pages"] == 2
        assert poll_state["health"] == "ok"
        # Every request carried the injected bearer credential.
        assert set(server.auth_values("Authorization")) == {f"Bearer {secret}"}
        # Cursor advanced across the two pages.
        assert server.param_values("page_key") == [None, "c2"]
        # Path is partner-user-scoped.
        assert all("/onramp/v1/buy/user/user-42/transactions" == p for p in server.paths)

        events = adapter._parse_poll_records(tenant_id, records, partner_user_ref="user-42")
        flat = json.dumps([e.payload for e in events])
        assert not [m for m in mp.SENSITIVE_MARKERS if m in flat], "sensitive fields leaked"
        assert all(e.stripped_keys for e in events)
        assert all(e.source == "polling" for e in events)

    async def test_cursor_recovery_resumes_from_stored_cursor(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        t3 = mp.coinbase_tx("cb3", "ONRAMP_TRANSACTION_STATUS_SUCCESS")
        transport, server = mp.coinbase_transport(secret=secret, pages={"c2": ([t3], None)})
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)

        records = await adapter._fetch_poll_records(
            tenant_id, poll_state={"cursor": "c2"}, partner_user_ref="user-42"
        )
        assert [r["transaction_id"] for r in records] == ["cb3"]
        assert server.param_values("page_key") == ["c2"]  # resumed from stored cursor

    async def test_rate_limit_retry_then_success(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        t1 = mp.coinbase_tx("cb1", "ONRAMP_TRANSACTION_STATUS_SUCCESS")
        transport, server = mp.coinbase_transport(
            secret=secret, pages={None: ([t1], None)}, rate_limit_first=2
        )
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)
        assert [r["transaction_id"] for r in records] == ["cb1"]
        assert poll_state["health"] == "ok"
        assert len(server.requests) == 3  # 2x429 (retried) + 1x200

    async def test_timeout_degrades_health_without_crashing(self):
        secret = "cb_secret"
        tenant_id = _tenant()
        transport, server = mp.coinbase_transport(
            secret=secret, pages={None: ([], None)}, timeout_first=99
        )
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop, max_retries=2)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)
        assert records == []
        assert poll_state["health"] == "timeout"
        assert len(server.requests) == 3  # initial + 2 retries, all timed out

    async def test_auth_failure_is_classified(self):
        tenant_id = _tenant()
        transport, _ = mp.coinbase_transport(secret="right", pages={None: ([], None)})
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, "wrong")  # mismatched secret -> 401

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)
        assert records == []
        assert poll_state["health"] == "auth_error"

    async def test_unconfigured_tenant_makes_no_request(self):
        transport, server = mp.coinbase_transport(secret="x", pages={None: ([], None)})
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop)
        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(_tenant(), poll_state=poll_state)
        assert records == []
        assert poll_state["health"] == "not_configured"
        assert server.requests == []  # never touched the network

    async def test_live_connection_test_ok_and_error(self):
        secret = "cb_secret"
        ok_tenant = _tenant()
        transport, _ = mp.coinbase_transport(secret=secret, pages={None: ([], None)})
        adapter = CoinbaseAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, ok_tenant, secret)
        result = await adapter._live_connection_test(ok_tenant)
        assert result.ok and result.status == "ok"

        bad_tenant = _tenant()
        bad_transport, _ = mp.coinbase_transport(secret="right", pages={None: ([], None)})
        bad_adapter = CoinbaseAdapter(http_transport=bad_transport, sleeper=_noop)
        await _configure(bad_adapter, bad_tenant, "wrong")
        bad = await bad_adapter._live_connection_test(bad_tenant)
        assert not bad.ok and bad.status == "error"


# ── MoonPay: time-window pagination ──────────────────────────────────────────


class TestMoonPayPull:
    async def test_time_window_pagination_and_watermark(self):
        secret = "mp_secret"
        tenant_id = _tenant()
        w0 = [
            mp.moonpay_tx("mp1", "completed", "2026-07-01T00:00:00+00:00"),
            mp.moonpay_tx("mp2", "completed", "2026-07-02T00:00:00+00:00"),
        ]
        # Second window (startDate == newest of w0) returns the remaining record.
        w1 = [mp.moonpay_tx("mp3", "completed", "2026-07-03T00:00:00+00:00")]
        transport, server = mp.moonpay_transport(
            secret=secret,
            windows={None: w0, "2026-07-02T00:00:00+00:00": w1,
                     "2026-07-03T00:00:00+00:00": []},
        )
        adapter = MoonPayAdapter(http_transport=transport, sleeper=_noop, max_retries=1)
        # limit=2 so a full first window forces a second window fetch.
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state, limit=2)
        got = [r["id"] for r in records]
        assert "mp1" in got and "mp2" in got and "mp3" in got
        # Persisted watermark is the newest updatedAt seen (next startDate).
        assert poll_state["next_cursor"] == "2026-07-03T00:00:00+00:00"
        assert set(server.auth_values("Authorization")) == {f"Api-Key {secret}"}
        assert server.param_values("startDate")[0] is None  # first sweep, no window

    async def test_auth_injection_and_redaction(self):
        secret = "mp_secret"
        tenant_id = _tenant()
        window = [mp.moonpay_tx("mp9", "completed", "2026-07-05T00:00:00+00:00")]
        transport, server = mp.moonpay_transport(secret=secret, windows={None: window})
        adapter = MoonPayAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state, limit=50)
        events = adapter._parse_poll_records(tenant_id, records)
        flat = json.dumps([e.payload for e in events])
        assert secret not in flat  # the API key never lands in a stored payload
        assert events and events[0].source == "polling"

    async def test_rate_limit_retry(self):
        secret = "mp_secret"
        tenant_id = _tenant()
        window = [mp.moonpay_tx("mp1", "completed", "2026-07-01T00:00:00+00:00")]
        transport, server = mp.moonpay_transport(
            secret=secret, windows={None: window}, rate_limit_first=1
        )
        adapter = MoonPayAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)
        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state, limit=50)
        assert [r["id"] for r in records] == ["mp1"]
        assert poll_state["health"] == "ok"
        assert len(server.requests) == 2  # 429 then 200


# ── Bridge: cursor pagination (starting_after) ───────────────────────────────


class TestBridgePull:
    async def test_cursor_pagination_auth_and_redaction(self):
        secret = "br_secret"
        tenant_id = _tenant()
        a1 = mp.bridge_activity("act1", "payment_processed")
        a2 = mp.bridge_activity("act2", "payment_processed")
        a3 = mp.bridge_activity("act3", "payment_processed")
        transport, server = mp.bridge_transport(
            secret=secret, pages={None: [a1, a2], "act2": [a3]}
        )
        adapter = BridgeAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)

        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(
            tenant_id, poll_state=poll_state, customer_id="cust1", limit=2
        )
        assert [r["id"] for r in records] == ["act1", "act2", "act3"]
        # Resume cursor is the last record id seen.
        assert poll_state["next_cursor"] == "act3"
        assert set(server.auth_values("Api-Key")) == {secret}
        assert server.param_values("starting_after") == [None, "act2"]
        assert all(
            "/v0/customers/cust1/virtual_accounts/history" == p for p in server.paths
        )

        events = adapter._parse_poll_records(tenant_id, records)
        flat = json.dumps([e.payload for e in events])
        # Raw bank account + routing numbers stripped before storage.
        assert "9876543210" not in flat and "021000021" not in flat
        assert all(e.stripped_keys for e in events)

    async def test_cursor_recovery_from_stored_cursor(self):
        secret = "br_secret"
        tenant_id = _tenant()
        a3 = mp.bridge_activity("act3", "payment_processed")
        transport, server = mp.bridge_transport(secret=secret, pages={"act2": [a3]})
        adapter = BridgeAdapter(http_transport=transport, sleeper=_noop)
        await _configure(adapter, tenant_id, secret)

        records = await adapter._fetch_poll_records(
            tenant_id, poll_state={"cursor": "act2"}, customer_id="cust1", limit=2
        )
        assert [r["id"] for r in records] == ["act3"]
        assert server.param_values("starting_after") == ["act2"]

    async def test_server_error_degrades_without_crash(self):
        secret = "br_secret"
        tenant_id = _tenant()
        # Wrong secret -> 401 auth_error path already covered; here force retries
        # exhausting on injected timeouts.
        transport, server = mp.bridge_transport(
            secret=secret, pages={None: []}, timeout_first=99
        )
        adapter = BridgeAdapter(http_transport=transport, sleeper=_noop, max_retries=1)
        await _configure(adapter, tenant_id, secret)
        poll_state = {"cursor": None}
        records = await adapter._fetch_poll_records(tenant_id, poll_state=poll_state)
        assert records == []
        assert poll_state["health"] == "timeout"
