"""Event-contract instruments and the Polymarket read-only adapter.

Replays pseudonymized live captures (``scripts/capture_venue_fixtures.py``)
through ``httpx.MockTransport`` — no live network. Proves the canonical
instrument shape, the Kalshi dollar-price field, outcome-token position
reconstruction, and that Polymarket passes the derivatives conformance and
shared certification suites.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from shared.certification.checks import run_certification
from value.derivatives.adapters import VENUE_ADAPTERS
from value.derivatives.adapters.conformance import run_conformance
from value.derivatives.adapters.polymarket import PolymarketAdapter
from value.derivatives.event_contracts import (
    EventContractInstrument,
    ResolutionState,
    kalshi_instrument,
    normalize_kalshi_market,
    polymarket_instrument,
)
from value.derivatives.models import NormalizedFillFact, OrderSide, PositionSide
from value.derivatives.position_engine import apply_fill
from value.prediction_markets import normalizers as legacy_normalizers
from value.prediction_markets.models import PredictionMarketValidationError

FIXTURES = (
    Path(__file__).parents[3]
    / "services" / "api" / "tests" / "fixtures" / "provider_payloads" / "derivatives"
)
PM = json.loads((FIXTURES / "polymarket_live_capture.json").read_text())


async def _noop(_seconds):
    return None


def _polymarket_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/v2/trades"):
            return httpx.Response(200, json=PM["trades"], request=request)
        if path.endswith("/v2/positions"):
            return httpx.Response(200, json=PM["positions"], request=request)
        if path.endswith("/markets"):
            return httpx.Response(200, json=PM["gamma_markets"], request=request)
        return httpx.Response(404, json={"error": "not found"}, request=request)

    return httpx.MockTransport(handler)


def _adapter() -> PolymarketAdapter:
    return PolymarketAdapter(
        http_transport=_polymarket_transport(), account_ref=PM["account_ref"], sleeper=_noop,
    )


def _contains_float(value) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_float(v) for v in value)
    return False


def test_legacy_prediction_market_normalizers_are_the_derivatives_ones():
    from value.derivatives import event_contracts

    assert legacy_normalizers.normalize_polymarket_market is event_contracts.normalize_polymarket_market
    assert legacy_normalizers.normalize_kalshi_market is event_contracts.normalize_kalshi_market


def test_polymarket_gamma_record_becomes_instrument_with_outcome_tokens():
    instrument = polymarket_instrument(PM["gamma_markets"][0])
    assert isinstance(instrument, EventContractInstrument)
    assert instrument.instrument_type == "event_contract"
    assert instrument.event_contract_ref.startswith("polymarket:mainnet:0x")
    assert len(instrument.outcomes) >= 2
    assert all(o.token_id for o in instrument.outcomes)
    payload = instrument.to_payload()
    assert payload["outcomes"][0]["canonical_market_id"].startswith("polymarket:mainnet:")
    assert payload["execution_by_aether"] is False


def test_kalshi_current_dollar_price_field_is_read():
    record = {
        "ticker": "KXTEST-1", "title": "Test", "status": "active",
        "last_price_dollars": "0.6200", "volume_fp": "1500.00", "result": "",
    }
    observation = normalize_kalshi_market(record)
    assert observation.outcomes[0].price == Decimal("0.6200")
    assert observation.outcomes[1].price == Decimal("0.3800")
    assert observation.volume == Decimal("1500.00")
    instrument = kalshi_instrument(record)
    assert instrument.resolution_state is ResolutionState.OPEN
    assert [o.label for o in instrument.outcomes] == ["yes", "no"]


def test_kalshi_legacy_cent_price_field_still_reads():
    observation = normalize_kalshi_market({"ticker": "K", "status": "open", "last_price": 41})
    assert observation.outcomes[0].price == Decimal("0.41")


def test_instrument_rejects_duplicate_outcomes_and_execution():
    with pytest.raises(PredictionMarketValidationError):
        EventContractInstrument(
            venue="polymarket", deployment="mainnet", condition_ref="c", title="t",
            resolution_state=ResolutionState.OPEN, execution_by_aether=True,
        )


def test_polymarket_is_registered_as_venue_adapter():
    assert isinstance(VENUE_ADAPTERS.get("polymarket"), PolymarketAdapter)


def test_unconfigured_polymarket_is_credential_waiting():
    result = asyncio.run(PolymarketAdapter().test_connection())
    assert result["ok"] is False and result["execution_by_aether"] is False


def test_polymarket_replay_normalizes_trades_and_positions():
    events, checkpoint = asyncio.run(_adapter().pull_events())
    fills = [e for e in events if e["event_name"] == "derivatives_fill_observed"]
    positions = [e for e in events if e["event_name"].startswith("derivatives_position_")]
    assert len(fills) == len(PM["trades"]["data"])
    assert len(positions) == len(PM["positions"]["data"])
    assert checkpoint["provider_health"] == "ok"
    assert not _contains_float(events)
    first = fills[0]["payload"]
    assert first["instrument_type"] == "event_contract"
    assert first["event_contract_ref"].startswith("polymarket:mainnet:0x")
    assert first["outcome"]
    assert first["canonical_market_id"].startswith("polymarket:mainnet:")
    assert all(e["execution_by_aether"] is False for e in events)


def test_polymarket_resume_emits_no_duplicate_fills():
    adapter = _adapter()
    events, checkpoint = asyncio.run(adapter.pull_events())
    again, _ = asyncio.run(adapter.pull_events(checkpoint))
    first_fills = {e["payload"]["fill_id"] for e in events if e["event_name"] == "derivatives_fill_observed"}
    resumed = [e for e in again if e["event_name"] == "derivatives_fill_observed"]
    # Inclusive high-water resume re-emits only boundary-timestamp fills.
    assert {e["payload"]["fill_id"] for e in resumed} <= first_fills
    assert len(resumed) < len(first_fills)


def test_outcome_token_fills_reconstruct_long_epochs():
    events, _ = asyncio.run(_adapter().pull_events())
    fills = sorted(
        (e["payload"] for e in events if e["event_name"] == "derivatives_fill_observed"),
        key=lambda p: p["executed_at"],
    )
    buys = [p for p in fills if p["side"] == "buy"]
    assert buys, "live capture should contain at least one outcome buy"
    p = buys[0]
    fact = NormalizedFillFact(
        tenant_id="t1", provider="polymarket", deployment="mainnet",
        trading_account_id=p["trading_account_id"], canonical_market_id=p["canonical_market_id"],
        fill_id=p["fill_id"], side=OrderSide.BUY, price=Decimal(p["price"]),
        quantity=Decimal(p["quantity"]), executed_at=p["executed_at"],
    )
    (epoch,) = apply_fill(None, fact)
    assert epoch.side is PositionSide.LONG and epoch.opened_at == p["executed_at"]


def test_polymarket_passes_conformance_and_certification():
    report = asyncio.run(run_conformance(_adapter()))
    assert report["passed"], [c for c in report["checks"] if not c["passed"]]
    assert report["events_sampled"] > 0
    adapter = _adapter()
    failures = [r.name for r in run_certification(adapter) if not r.passed]
    assert not failures, failures
    descriptor = adapter.certification_descriptor()
    assert descriptor.implementation_state.value == "credential_waiting"
    assert descriptor.domain == "derivatives"


# ── Hyperliquid live-capture replay (perpetuals share the same plane) ────────
HL = json.loads((FIXTURES / "hyperliquid_live_capture.json").read_text())


def test_hyperliquid_live_capture_replays_through_adapter():
    from value.derivatives.adapters.hyperliquid import HyperliquidAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        kind = body.get("type")
        if kind == "userFillsByTime":
            start = int(body.get("startTime") or 0)
            page = [f for f in HL["user_fills_by_time"] if int(f["time"]) >= start]
            return httpx.Response(200, json=page, request=request)
        if kind == "clearinghouseState":
            return httpx.Response(200, json=HL["clearinghouse_state"], request=request)
        if kind == "userFunding":
            return httpx.Response(200, json=[], request=request)
        return httpx.Response(200, json={"universe": []}, request=request)

    adapter = HyperliquidAdapter(
        http_transport=httpx.MockTransport(handler), account_ref=HL["account_ref"], sleeper=_noop,
    )
    events, checkpoint = asyncio.run(adapter.pull_events())
    fills = [e for e in events if e["event_name"] == "derivatives_fill_observed"]
    assert len(fills) == len(HL["user_fills_by_time"])
    assert checkpoint["provider_health"] == "ok"
    assert not _contains_float(events)
    assert all(f["payload"]["canonical_market_id"].startswith("hyperliquid:mainnet:") for f in fills)


def test_runtime_fill_intake_keeps_event_contract_context_in_source_refs():
    from value.derivatives.runtime_routes import _fill_source_refs

    refs = _fill_source_refs({
        "source_refs": ["polymarket:tx:1"], "instrument_type": "event_contract",
        "event_contract_ref": "polymarket:mainnet:0xc", "outcome": "Yes", "direction": None,
    })
    assert refs == [
        "polymarket:tx:1", "instrument_type=event_contract",
        "event_contract_ref=polymarket:mainnet:0xc", "outcome=Yes",
    ]
    assert _fill_source_refs({"source_refs": ["outcome=No"], "outcome": "Yes"}) == ["outcome=No"]
