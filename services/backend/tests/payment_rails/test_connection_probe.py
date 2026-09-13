"""Read-only connection-probe contract for the pull-capable payment rails.

Every pull adapter (Coinbase / MoonPay / Bridge) exposes an authenticated
``_live_connection_test`` that issues exactly ONE bounded, READ-ONLY (HTTP
``GET``) health ping through the injectable mock transport — NO live network.
This module proves the probe contract *uniformly* across all three providers,
plus the ``test_connection`` orchestration branches (not-configured
short-circuit, local-mode skip, non-local live routing).

``test_polling.py`` already covers ``_fetch_poll_records`` pagination and a
single Coinbase ok/error connection test; this file closes the remaining gaps:
MoonPay + Bridge probe parity, the read-only (GET-only) invariant across every
outcome, rate-limit / timeout classification on the probe path, and the
``test_connection`` mode routing for pull adapters.
"""

from __future__ import annotations

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


# ── Per-provider probe harness ───────────────────────────────────────────────
# Each factory builds an adapter wired to that provider's mock transport with an
# empty-but-valid dataset. ``server_secret`` is what the mock server expects on
# the wire; the *vault* secret is configured separately by each test so the
# wrong-secret (auth-error) path can diverge the two. ``inject`` forwards
# ``rate_limit_first`` / ``timeout_first`` to the transport for failure modes.


def _coinbase(server_secret: str, **inject):
    transport, server = mp.coinbase_transport(
        secret=server_secret, pages={None: ([], None)}, **inject
    )
    return CoinbaseAdapter(http_transport=transport, sleeper=_noop), server


def _moonpay(server_secret: str, **inject):
    transport, server = mp.moonpay_transport(
        secret=server_secret, windows={None: []}, **inject
    )
    return MoonPayAdapter(http_transport=transport, sleeper=_noop), server


def _bridge(server_secret: str, **inject):
    transport, server = mp.bridge_transport(
        secret=server_secret, pages={None: []}, **inject
    )
    return BridgeAdapter(http_transport=transport, sleeper=_noop), server


PROBES = {"coinbase": _coinbase, "moonpay": _moonpay, "bridge": _bridge}


def _assert_all_get(server) -> None:
    """The probe path must never issue a non-GET (mutating) verb."""
    assert server.requests, "expected at least one recorded request"
    assert all(r.method == "GET" for r in server.requests), (
        f"connection probe issued non-GET verbs: {[r.method for r in server.requests]}"
    )


@pytest.mark.parametrize("provider", ["coinbase", "moonpay", "bridge"])
class TestReadOnlyProbe:
    """`_live_connection_test` contract, proven identically for every pull rail."""

    async def test_ok_probe_is_single_readonly_get(self, provider):
        secret = "sek_ok"
        adapter, server = PROBES[provider](secret)
        tenant = _tenant()
        await _configure(adapter, tenant, secret)

        result = await adapter._live_connection_test(tenant)

        assert result.ok is True and result.status == "ok"
        assert result.provider == provider
        # Bounded + read-only: exactly one request, and it is a GET.
        assert len(server.requests) == 1
        _assert_all_get(server)

    async def test_wrong_secret_is_auth_error_still_readonly(self, provider):
        adapter, server = PROBES[provider]("right-secret")
        tenant = _tenant()
        await _configure(adapter, tenant, "wrong-secret")

        result = await adapter._live_connection_test(tenant)

        assert result.ok is False and result.status == "error"
        assert "auth_error" in result.detail
        _assert_all_get(server)  # a rejected probe is still a read

    async def test_rate_limited_exhaustion_is_error(self, provider):
        adapter, server = PROBES[provider]("sek", rate_limit_first=99)
        tenant = _tenant()
        await _configure(adapter, tenant, "sek")

        result = await adapter._live_connection_test(tenant)

        assert result.ok is False and result.status == "error"
        assert "rate_limited" in result.detail
        _assert_all_get(server)  # every retry attempt is a GET

    async def test_timeout_is_error(self, provider):
        adapter, server = PROBES[provider]("sek", timeout_first=99)
        tenant = _tenant()
        await _configure(adapter, tenant, "sek")

        result = await adapter._live_connection_test(tenant)

        assert result.ok is False and result.status == "error"
        assert "timeout" in result.detail
        _assert_all_get(server)

    async def test_not_configured_makes_no_request(self, provider):
        adapter, server = PROBES[provider]("sek")

        result = await adapter._live_connection_test(_tenant())

        assert result.ok is False and result.status == "not_configured"
        assert server.requests == []  # never touched the network


class TestConnectionOrchestration:
    """`test_connection` mode routing for pull adapters (webhook-only rails are
    covered in test_certification.py)."""

    async def test_local_mode_skips_live_probe(self):
        # Module default AETHER_ENV=local: a configured pull adapter resolves ok
        # WITHOUT any network IO — the live probe is skipped in local mode.
        adapter, server = _coinbase("sek")
        tenant = _tenant()
        await _configure(adapter, tenant, "sek")

        result = await adapter.test_connection(tenant)

        assert result.ok is True and result.status == "ok"
        assert "local mode" in result.detail
        assert server.requests == []  # live probe skipped

    async def test_non_local_configured_runs_readonly_probe(self, monkeypatch):
        monkeypatch.setenv("AETHER_ENV", "production")
        adapter, server = _bridge("sek")
        tenant = _tenant()
        await _configure(adapter, tenant, "sek")

        result = await adapter.test_connection(tenant)

        assert result.ok is True and result.status == "ok"
        assert len(server.requests) == 1
        _assert_all_get(server)

    async def test_not_configured_short_circuits_without_network(self, monkeypatch):
        # Even outside local mode, a missing credential returns a typed
        # not_configured — never a 500, and never a network call.
        monkeypatch.setenv("AETHER_ENV", "production")
        adapter, server = _moonpay("sek")

        result = await adapter.test_connection(_tenant())

        assert result.ok is False and result.status == "not_configured"
        assert server.requests == []
