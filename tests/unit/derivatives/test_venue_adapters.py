"""Read-only venue adapter integration tests — REST backfill against in-process
mock venue servers (httpx.MockTransport, NO live network).

Proves per venue: authenticated read request construction, cursor pagination,
rate-limit + retry, timeout classification, deterministic Decimal-only
normalization, cursor persistence, read-only scope rejection, and that each
adapter passes both the derivatives conformance suite and the shared
credentialless certification suite with zero failures — with a live client.
"""

from __future__ import annotations

import asyncio

import pytest

import mock_venues as mv

from services.derivatives.adapters.conformance import run_conformance
from services.derivatives.adapters.drift import DriftAdapter
from services.derivatives.adapters.dydx import DydxAdapter
from services.derivatives.adapters.gmx import GmxAdapter
from services.derivatives.adapters.hyperliquid import HyperliquidAdapter
from services.derivatives.models import ReadOnlyCredentialError
from shared.certification.checks import run_certification


async def _noop(_seconds):  # deterministic: never actually sleep during retries
    return None


def _contains_float(value) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_float(v) for v in value)
    return False


# ── builders returning a live-clienned adapter per venue ─────────────────────
def _hyperliquid(**kw):
    transport, server = mv.hyperliquid_transport(
        fills=[mv.hl_fill(1, 1000, "B"), mv.hl_fill(2, 1001, "A"), mv.hl_fill(3, 1002, "B")],
        clearinghouse=mv.HL_CLEARINGHOUSE,
        funding=[{"time": 4000, "delta": {"coin": "BTC", "usdc": "-1.25"}}],
        **kw,
    )
    return HyperliquidAdapter(http_transport=transport, account_ref="0xabc", sleeper=_noop), server


def _dydx(**kw):
    transport, server = mv.dydx_transport(
        fill_pages={None: ([mv.dydx_fill("d1"), mv.dydx_fill("d2", "SELL")], "c2"),
                    "c2": ([mv.dydx_fill("d3")], None)},
        orders=[{"id": "o1", "side": "BUY", "size": "0.10", "price": "61000",
                 "status": "OPEN", "type": "LIMIT", "market": "BTC-USD"}],
        positions=[{"market": "BTC-USD", "side": "LONG", "size": "0.30",
                    "entryPrice": "60500", "unrealizedPnl": "5", "realizedPnl": "0",
                    "status": "OPEN"}],
        **kw,
    )
    return DydxAdapter(http_transport=transport, account_ref="dydx1", sleeper=_noop), server


def _gmx(**kw):
    transport, server = mv.gmx_transport(
        trades=[mv.gmx_trade("g1", 300), mv.gmx_trade("g2", 200, is_long=False),
                mv.gmx_trade("g3", 100)],
        **kw,
    )
    adapter = GmxAdapter(http_transport=transport, account_ref="0xabc", sleeper=_noop)
    adapter.page_first = 2  # force multi-page pagination
    return adapter, server


def _drift(**kw):
    transport, server = mv.drift_transport(
        trade_pages={None: ([mv.drift_trade("dr1", 1000), mv.drift_trade("dr2", 1001, direction="short")], "2"),
                     "2": ([mv.drift_trade("dr3", 1002)], None)},
        funding=[{"recordId": "f1", "marketName": "SOL-PERP", "amount": "-0.5", "ts": 4000}],
        **kw,
    )
    return DriftAdapter(http_transport=transport, account_ref="auth1", sleeper=_noop), server


ALL_BUILDERS = {"hyperliquid": _hyperliquid, "dydx": _dydx, "gmx": _gmx, "drift": _drift}


# ── REST backfill + normalization ────────────────────────────────────────────
async def test_hyperliquid_backfill_normalizes_all_streams():
    adapter, server = _hyperliquid()
    events, checkpoint = await adapter.pull_events(None)
    names = [e["event_name"] for e in events]
    assert names.count("derivatives_fill_observed") == 3
    assert "derivatives_funding_payment_observed" in names
    assert "derivatives_position_opened_observed" in names
    assert "derivatives_margin_snapshot_observed" in names
    # ETH position has szi=0 → skipped (no spurious flat position)
    assert sum(1 for e in events if e["event_name"] == "derivatives_position_opened_observed") == 1
    # exact decimals, no floats
    assert not any(_contains_float(e) for e in events)
    fill = next(e for e in events if e["payload"].get("fill_id") == "1")
    assert fill["payload"]["price"] == "60000"
    assert fill["payload"]["quantity"] == "0.25"
    assert fill["payload"]["liquidity_role"] == "taker"
    assert fill["execution_by_aether"] is False  # never claims execution
    assert checkpoint["provider_health"] == "ok"


async def test_dydx_backfill_paginates_and_normalizes():
    adapter, server = _dydx()
    events, checkpoint = await adapter.pull_events(None)
    assert sum(1 for e in events if e["event_name"] == "derivatives_fill_observed") == 3
    assert any(e["event_name"] == "derivatives_order_observed" for e in events)
    assert any(e["event_name"] == "derivatives_position_opened_observed" for e in events)
    # pagination: intra-sweep followed the "c2" next-page token
    fills_cursors = [c for c in server.param_values("pageCursor")]
    assert "c2" in fills_cursors
    # cross-sweep resume checkpoint is the fills' high-water mark (createdAt)
    assert checkpoint["cursors"]["raw_fill"] == "2026-07-05T00:00:00.000Z"
    assert not any(_contains_float(e) for e in events)


async def test_gmx_public_read_path_paginates_by_timestamp():
    adapter, server = _gmx()
    events, _ = await adapter.pull_events(None)
    fills = [e for e in events if e["event_name"] == "derivatives_fill_observed"]
    assert len(fills) == 3
    # multi-page: tsLt advanced across at least 3 subgraph POSTs
    assert len(server.requests) >= 3
    assert fills[1]["payload"]["side"] == "sell"  # g2 isLong=False
    assert not any(_contains_float(e) for e in events)


async def test_drift_read_path_paginates_and_normalizes_funding():
    adapter, server = _drift()
    events, _ = await adapter.pull_events(None)
    assert sum(1 for e in events if e["event_name"] == "derivatives_fill_observed") == 3
    assert any(e["event_name"] == "derivatives_funding_payment_observed" for e in events)
    assert "2" in server.param_values("page")
    assert not any(_contains_float(e) for e in events)


# ── determinism + idempotency + cursor persistence ───────────────────────────
@pytest.mark.parametrize("venue", list(ALL_BUILDERS))
async def test_pull_events_is_idempotent_per_checkpoint(venue):
    import json
    adapter, _ = ALL_BUILDERS[venue]()
    first, cp = await adapter.pull_events(None)
    second, _ = await adapter.pull_events(None)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    # Resuming from the persisted checkpoint re-observes at most the boundary
    # record (at-least-once) and NEVER a brand-new fill id — cursor persistence
    # bounds re-delivery; downstream idempotency dedupes the boundary.
    first_ids = {e["payload"]["fill_id"] for e in first if e["event_name"] == "derivatives_fill_observed"}
    resumed, _ = await adapter.pull_events(cp)
    resumed_ids = {e["payload"]["fill_id"] for e in resumed if e["event_name"] == "derivatives_fill_observed"}
    assert resumed_ids <= first_ids


async def test_resume_delivers_only_new_fills_after_checkpoint():
    """Cursor persistence: a fill arriving after the checkpoint is delivered on
    resume, while the earlier fills are not re-delivered as new."""
    adapter, _ = _hyperliquid()
    _, checkpoint = await adapter.pull_events(None)  # fills at t=1000,1001,1002

    # A new fill (t=1003) appears; resume the SAME account from the checkpoint.
    transport, _ = mv.hyperliquid_transport(
        fills=[mv.hl_fill(1, 1000), mv.hl_fill(2, 1001, "A"), mv.hl_fill(3, 1002),
               mv.hl_fill(4, 1003)],
        clearinghouse=mv.HL_CLEARINGHOUSE,
    )
    resumed_adapter = HyperliquidAdapter(http_transport=transport, account_ref="0xabc", sleeper=_noop)
    events, _ = await resumed_adapter.pull_events(checkpoint)
    fill_ids = {e["payload"]["fill_id"] for e in events if e["event_name"] == "derivatives_fill_observed"}
    assert "4" in fill_ids  # the new fill is delivered
    assert "1" not in fill_ids  # pre-checkpoint fills are not re-delivered


# ── rate-limit + timeout resilience ──────────────────────────────────────────
async def test_hyperliquid_retries_through_rate_limit():
    adapter, server = _hyperliquid(rate_limit_first=2)
    events, checkpoint = await adapter.pull_events(None)
    assert sum(1 for e in events if e["event_name"] == "derivatives_fill_observed") == 3
    assert checkpoint["provider_health"] == "ok"
    assert len(server.requests) >= 3  # 2 retried 429s + success


async def test_dydx_retries_through_timeout():
    adapter, server = _dydx(timeout_first=1)
    events, checkpoint = await adapter.pull_events(None)
    assert sum(1 for e in events if e["event_name"] == "derivatives_fill_observed") == 3
    assert checkpoint["provider_health"] == "ok"


async def test_test_connection_classifies_server_error():
    import httpx
    from services.derivatives.connectors.transport import RestBackfillClient

    def handler(request):
        return httpx.Response(500, json={"error": "boom"}, request=request)

    client = RestBackfillClient(http_transport=httpx.MockTransport(handler), sleeper=_noop)
    adapter = HyperliquidAdapter(rest_client=client, account_ref="0xabc")
    result = await adapter.test_connection()
    assert result["ok"] is False
    assert result["state"] == "server_error"
    assert result["execution_by_aether"] is False


async def test_unconfigured_adapter_is_credential_waiting():
    adapter = HyperliquidAdapter()  # no client injected
    result = await adapter.test_connection()
    assert result["ok"] is False
    assert result["state"] == "not_configured"
    events, cp = await adapter.pull_events(None)
    assert events == []
    assert cp["provider_health"] == "not_configured"


# ── read-only credential authority + scope rejection ─────────────────────────
@pytest.mark.parametrize("venue", list(ALL_BUILDERS))
def test_validate_config_refuses_trade_authority(venue):
    adapter, _ = ALL_BUILDERS[venue]()
    with pytest.raises(ValueError):
        adapter.validate_config({"authority_type": "trade"})
    adapter.validate_config({"authority_type": "read_only"})  # accepted


@pytest.mark.parametrize("venue", list(ALL_BUILDERS))
def test_validate_config_rejects_mutating_scopes(venue):
    adapter, _ = ALL_BUILDERS[venue]()
    with pytest.raises(ReadOnlyCredentialError):
        adapter.validate_config({"authority_type": "read_only", "scopes": ["read", "orders:write"]})
    with pytest.raises(ReadOnlyCredentialError):
        adapter.validate_config({"authority_type": "read_only", "scopes": ["withdraw"]})
    adapter.validate_config({"authority_type": "read_only", "scopes": ["account:read", "fills:read"]})


# ── conformance + certification with a live client ───────────────────────────
@pytest.mark.parametrize("venue", list(ALL_BUILDERS))
async def test_conformance_passes_with_live_client(venue):
    adapter, _ = ALL_BUILDERS[venue]()
    report = await run_conformance(adapter)
    failing = [c for c in report["checks"] if not c["passed"]]
    assert report["passed"], failing
    assert report["events_sampled"] > 0


@pytest.mark.parametrize("venue", list(ALL_BUILDERS))
def test_certification_passes_with_zero_failures(venue):
    adapter, _ = ALL_BUILDERS[venue]()
    results = run_certification(adapter)
    failures = [r.name for r in results if not r.passed]
    assert not failures, failures
    descriptor = adapter.certification_descriptor()
    assert descriptor.implementation_state.value == "credential_waiting"
    assert descriptor.domain == "derivatives"


# ── converged connector surface (Bronze fetch) + import fallback ─────────────
async def test_fetch_fills_returns_bronze_observations():
    adapter, _ = _hyperliquid()
    bronze = await adapter.fetch_fills(account_ref="0xabc")
    assert len(bronze) == 3
    assert all(obs.record_type == "raw_fill" for obs in bronze)
    assert all(obs.execution_by_aether is False for obs in bronze)


async def test_hyperliquid_connector_real_fetch_and_normalize():
    from services.derivatives.connectors.hyperliquid import HyperliquidConnector

    transport, _ = mv.hyperliquid_transport(
        fills=[mv.hl_fill(1, 1000, "B"), mv.hl_fill(2, 1001, "A")],
        clearinghouse=mv.HL_CLEARINGHOUSE,
    )
    connector = HyperliquidConnector(tenant_id="t1", http_transport=transport, sleeper=_noop)
    bronze = await connector.fetch_fills(account_ref="0xabc")
    assert len(bronze) == 2
    facts = connector.normalize(bronze[0])
    assert facts and str(facts[0].price) == "60000"
    assert facts[0].execution_by_aether is False
    checkpoint = connector.checkpoint(bronze)
    assert checkpoint is not None and checkpoint.connector_id == "hyperliquid"


def test_import_fallback_still_parses_partner_records():
    """Partners without credentials use the explicit CSV/JSON/NDJSON fallback."""
    from services.derivatives.connectors.generic_import import parse_import_payload

    payload = (
        '{"source_record_id":"f1","account":"0xabc","market":"BTC","side":"buy",'
        '"price":"100","quantity":"2","executed_at":"2026-01-01T00:00:00Z"}'
    )
    report = parse_import_payload(
        tenant_id="t1", provider="tenant_import", deployment="csv", batch_id="b1",
        payload=payload, content_type="ndjson", mapping_version="v1",
    )
    assert report.accepted_rows == 1
    assert report.observations[0].record_type == "raw_fill"
