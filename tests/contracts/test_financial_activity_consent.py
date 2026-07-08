"""Contract test: 5 agent trading events must require financial_activity consent."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_financial_activity_gates_sensitive_agent_trading_events():
    registry = json.loads((ROOT / "packages/shared/contracts/event-registry.json").read_text())
    by_type = {event["type"]: event for event in registry["events"]}
    sensitive_trading_events = [
        "agent_trade_order_observed",
        "agent_trade_fill_observed",
        "agent_position_observed",
        "agent_portfolio_snapshot_observed",
        "agent_performance_snapshot_observed",
    ]
    for event_type in sensitive_trading_events:
        assert by_type[event_type]["requiredPurposes"] == ["financial_activity"], (
            f"{event_type} must require financial_activity consent, got {by_type[event_type]['requiredPurposes']}"
        )
