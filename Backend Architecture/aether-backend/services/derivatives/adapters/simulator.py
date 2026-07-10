"""Deterministic simulator adapter — the reference implementation every
conformance rule is proven against. MOCKED_LOCAL by definition; it exists
so the pipeline, state machines, and P&L can be exercised end-to-end
without any venue credentials."""

from __future__ import annotations

import random
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.adapters.base import DerivativesAdapter

_VENUE = "venue:simulated"
_MARKET = "simulated:btc-perp"
_ACCOUNT = "sim-account-1"


def _scenario(seed: int) -> list[dict[str, Any]]:
    """One canonical account lifecycle: link -> order -> fills -> position
    open/close -> funding/fee/margin -> pnl snapshot. Deterministic per seed;
    all amounts are decimal strings."""
    rng = random.Random(seed)
    base_price = 60_000 + rng.randrange(0, 5_000)
    quantity = "0.500000000000000000"
    half = "0.250000000000000000"

    def event(name: str, **payload: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "event_name": name,
            "payload": {
                "venue_id": _VENUE,
                "canonical_market_id": _MARKET,
                "trading_account_id": _ACCOUNT,
                **payload,
            },
            "execution_by_aether": False,
        }
        return record

    return [
        event("derivatives_account_linked", external_account_ref=_ACCOUNT,
              authority_type="read_only", connector_state="configured"),
        event("derivatives_order_observed", order_id="sim-ord-1", order_status="pending",
              order_side="buy", order_type="limit", quantity=quantity,
              limit_price=f"{base_price}.000000000000000000"),
        event("derivatives_order_updated_observed", order_id="sim-ord-1", order_status="open"),
        event("derivatives_fill_observed", fill_id="sim-fill-1", order_id="sim-ord-1",
              side="buy", price=f"{base_price}.000000000000000000", quantity=half,
              liquidity_role="maker", executed_at="2026-07-08T12:00:00Z"),
        event("derivatives_order_updated_observed", order_id="sim-ord-1",
              order_status="partially_filled"),
        event("derivatives_fill_observed", fill_id="sim-fill-2", order_id="sim-ord-1",
              side="buy", price=f"{base_price + 10}.000000000000000000", quantity=half,
              liquidity_role="taker", executed_at="2026-07-08T12:00:05Z"),
        event("derivatives_order_updated_observed", order_id="sim-ord-1", order_status="filled"),
        event("derivatives_position_opened_observed", position_id="sim-pos-1",
              side="long", status="open", size=quantity,
              entry_price=f"{base_price + 5}.000000000000000000"),
        event("derivatives_funding_payment_observed", funding_payment_id="sim-fund-1",
              position_id="sim-pos-1", amount="-1.250000000000000000", asset_id="usdc",
              settled_at="2026-07-08T16:00:00Z"),
        event("derivatives_fee_observed", trading_fee_id="sim-fee-1", fee_type="taker",
              amount="0.750000000000000000", asset_id="usdc",
              charged_at="2026-07-08T12:00:05Z"),
        event("derivatives_margin_snapshot_observed", margin_snapshot_id="sim-margin-1",
              margin_mode="cross", maintenance_margin="150.000000000000000000",
              initial_margin="300.000000000000000000",
              margin_utilization="0.120000000000000000",
              observed_at="2026-07-08T16:00:00Z"),
        event("derivatives_position_closed_observed", position_id="sim-pos-1",
              side="flat", status="closed", size="0",
              realized_pnl="42.500000000000000000"),
        event("derivatives_pnl_snapshot_materialized", pnl_snapshot_id="sim-pnl-1",
              realized_pnl="42.500000000000000000", unrealized_pnl="0",
              gross_exposure="0", net_exposure="0", accounting_method="average_entry",
              as_of="2026-07-08T17:00:00Z"),
    ]


class SimulatorAdapter(DerivativesAdapter):
    adapter_id = "simulator"
    display_name = "Deterministic Simulator (reference)"
    implementation_status = ImplementationStatus.MOCKED_LOCAL
    capabilities = (
        "reference_data", "account_snapshot", "order_lifecycle", "position",
        "funding", "reconciliation",
    )
    supported_instrument_types = ("perpetual_future",)
    authentication_model = "none"
    known_limitations = (
        "Synthetic deterministic scenario generator — no venue connectivity. "
        "Exists to prove the pipeline and the conformance suite."
    )

    def __init__(self, seed: int = 42, batch_size: int = 4) -> None:
        self.seed = seed
        self.batch_size = batch_size

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "detail": "simulator has no external dependency"}

    async def pull_events(
        self, checkpoint: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        cursor = int((checkpoint or {}).get("cursor", 0))
        scenario = _scenario(self.seed)
        window = scenario[cursor: cursor + self.batch_size]
        new_cursor = min(cursor + len(window), len(scenario))
        return window, {"cursor": new_cursor}
