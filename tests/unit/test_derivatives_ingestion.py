"""PR2 derivatives connector, import, accounting, reconciliation foundation tests."""
from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@pytest.fixture()
def deriv():
    original = list(sys.path)
    for name in list(sys.modules):
        if name == "services" or name.startswith("services."):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield SimpleNamespace(
            models=importlib.import_module("services.derivatives.models"),
            generic=importlib.import_module("services.derivatives.connectors.generic_import"),
            hyperliquid=importlib.import_module("services.derivatives.connectors.hyperliquid"),
            position=importlib.import_module("services.derivatives.position_engine"),
            reconciliation=importlib.import_module("services.derivatives.reconciliation"),
            replay=importlib.import_module("services.derivatives.replay"),
        )
    finally:
        sys.path[:] = original
        for name in list(sys.modules):
            if name == "services" or name.startswith("services."):
                sys.modules.pop(name, None)


def test_read_only_credentials_reject_mutating_scopes(deriv):
    with pytest.raises(deriv.models.ReadOnlyCredentialError):
        deriv.models.validate_read_only_scopes(["read", "orders:write", "withdraw"])
    deriv.models.validate_read_only_scopes(["read", "account:read", "fills:read"])


def test_generic_import_validates_rows_and_quarantines_bad_records(deriv):
    payload = "\n".join([
        '{"source_record_id":"f1","account":"0xabc","market":"BTC","side":"buy","price":"100","quantity":"2","executed_at":"2026-01-01T00:00:00Z"}',
        '{"source_record_id":"f2","account":"0xabc","market":"BTC","side":"sell","price":100.25,"quantity":"1","executed_at":"2026-01-01T00:01:00Z"}',
        '{"source_record_id":"f3","account":"0xabc","market":"BTC","side":"sell","price":"110","executed_at":"2026-01-01T00:02:00Z"}',
    ])
    report = deriv.generic.parse_import_payload(
        tenant_id="tenant-a",
        provider="tenant_import",
        deployment="csv",
        batch_id="batch-1",
        payload=payload,
        content_type="ndjson",
        mapping_version="v1",
    )
    assert report.accepted_rows == 1
    assert report.quarantined_rows == 2
    assert report.observations[0].idempotency_key == "tenant-a:tenant_import:csv:0xabc:batch-1:f1"
    assert {err.row_number for err in report.row_errors} == {2, 3}


def test_hyperliquid_normalizes_fill_with_decimal_and_idempotency(deriv):
    connector = deriv.hyperliquid.HyperliquidConnector(tenant_id="tenant-a")
    obs = deriv.models.BronzeObservation(
        tenant_id="tenant-a",
        provider="hyperliquid",
        deployment="mainnet",
        record_type="raw_fill",
        source_record_id="hl-fill-1",
        raw_payload={"hash": "h1", "account": "0xabc", "coin": "BTC", "side": "B", "px": "100.5", "sz": "0.25", "fee": "0.01", "liquidity": "taker", "time": "2026-01-01T00:00:00Z"},
        observed_at="2026-01-01T00:00:01Z",
        idempotency_key="tenant-a:hyperliquid:mainnet:0xabc:hl-fill-1",
    )
    fill = connector.normalize(obs)[0]
    assert fill.price == Decimal("100.5")
    assert fill.quantity == Decimal("0.25")
    assert fill.idempotency_key == "tenant-a:hyperliquid:mainnet:acct_0xabc:hyperliquid:hl-fill-1"
    assert fill.execution_by_aether is False


def test_position_engine_reconstructs_epochs_and_net_pnl(deriv):
    F = deriv.models.NormalizedFillFact
    SourceRef = deriv.models.SourceRef
    OrderSide = deriv.models.OrderSide
    fills = [
        F("tenant-a", "import", "file", "acct", "BTC-PERP", "f1", OrderSide.BUY, Decimal("100"), Decimal("2"), "t1", fee_amount=Decimal("1"), source_ref=SourceRef("import", "f1", "t1")),
        F("tenant-a", "import", "file", "acct", "BTC-PERP", "f2", OrderSide.SELL, Decimal("110"), Decimal("1"), "t2", fee_amount=Decimal("1"), source_ref=SourceRef("import", "f2", "t2")),
        F("tenant-a", "import", "file", "acct", "BTC-PERP", "f3", OrderSide.SELL, Decimal("90"), Decimal("1"), "t3", fee_amount=Decimal("1"), source_ref=SourceRef("import", "f3", "t3")),
    ]
    state = None
    for fill in fills:
        state = deriv.position.apply_fill(state, fill)[-1]
    assert state.status == deriv.models.PositionStatus.CLOSED
    assert state.realized_pnl == Decimal("0")
    assert state.net_realized_pnl == Decimal("-3")
    assert state.closed_at == "t3"


def test_reconciliation_detects_variance(deriv):
    state = deriv.models.PositionEpochState("tenant-a", "acct", "BTC-PERP", "epoch-1", size=Decimal("1"), status=deriv.models.PositionStatus.OPEN)
    variance = deriv.reconciliation.reconcile_position_size(computed=state, observed_size=Decimal("1.5"), source_ref="snapshot-1")
    assert variance is not None
    assert variance.variance_type == "position_size_mismatch"
    assert variance.difference == Decimal("-0.5")
    assert variance.status == "variance_detected"


def test_replay_is_deterministic(deriv):
    observations = [
        deriv.models.BronzeObservation("tenant-a", "hyperliquid", "mainnet", "raw_fill", "2", {"hash": "2", "account": "0xabc", "coin": "BTC", "side": "A", "px": "110", "sz": "1", "fee": "0", "time": "t2"}, "t2", "k2"),
        deriv.models.BronzeObservation("tenant-a", "hyperliquid", "mainnet", "raw_fill", "1", {"hash": "1", "account": "0xabc", "coin": "BTC", "side": "B", "px": "100", "sz": "1", "fee": "0", "time": "t1"}, "t1", "k1"),
    ]
    first = deriv.replay.replay_hyperliquid_fills(observations)
    second = deriv.replay.replay_hyperliquid_fills(list(reversed(observations)))
    assert first == second
    assert first.status == deriv.models.PositionStatus.CLOSED
    assert first.realized_pnl == Decimal("10")
