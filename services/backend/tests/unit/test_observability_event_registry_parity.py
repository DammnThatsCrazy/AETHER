"""
Parity tests: All 47 new agentic observability events in EVENT_REGISTRY.md
must exist in packages/shared/events.ts EventType.

Parses events.ts as text to avoid any import chain issues.
"""

from __future__ import annotations

import os
import re

import pytest

# ── All 47 new events from EVENT_REGISTRY.md ──────────────────────────────

EXPECTED_AGENTIC_OBS_EVENTS = {
    # Agentic account / MCP (12)
    "agentic_account_observed",
    "agentic_account_connected_observed",
    "agentic_account_disconnected_observed",
    "agent_budget_observed",
    "agent_budget_changed_observed",
    "agent_permission_observed",
    "agent_mcp_connection_observed",
    "agent_tool_observed",
    "agent_tool_invocation_observed",
    "agent_activity_observed",
    "agent_risk_signal_observed",
    "agent_notification_observed",
    # Robinhood-style trading observation (9)
    "agent_strategy_observed",
    "agent_trade_intent_observed",
    "agent_trade_order_observed",
    "agent_trade_fill_observed",
    "agent_trade_rejection_observed",
    "agent_position_observed",
    "agent_portfolio_snapshot_observed",
    "agent_performance_snapshot_observed",
    "agent_disconnect_observed",
    # AgentMail-style communication observation (15)
    "agent_inbox_observed",
    "agent_email_address_observed",
    "agent_thread_observed",
    "agent_message_received_observed",
    "agent_message_sent_observed",
    "agent_reply_observed",
    "agent_attachment_observed",
    "agent_attachment_parsed_observed",
    "agent_otp_detected_observed",
    "agent_invoice_detected_observed",
    "agent_receipt_detected_observed",
    "agent_calendar_intent_observed",
    "agent_support_route_observed",
    "agent_semantic_search_observed",
    "agent_data_extraction_observed",
    # x402 protocol observation (11)
    "x402_resource_request_observed",
    "x402_challenge_observed",
    "x402_payment_requirement_observed",
    "x402_signature_observed",
    "x402_verification_observed",
    "x402_settlement_observed",
    "x402_resource_access_observed",
    "x402_resource_access_denied_observed",
    "x402_failure_observed",
    "x402_replay_risk_observed",
    "x402_provider_observed",
}


def _load_ts_event_types() -> set[str]:
    """Parse EventType union from packages/shared/events.ts as text."""
    repo_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", ".."
    ))
    ts_path = os.path.join(repo_root, "packages", "shared", "events.ts")
    if not os.path.exists(ts_path):
        pytest.skip(f"packages/shared/events.ts not found at {ts_path}")
    with open(ts_path) as f:
        content = f.read()
    return set(re.findall(r"[|]\s*['\"]([a-z_0-9]+)['\"]", content))


@pytest.mark.parametrize("event_name", sorted(EXPECTED_AGENTIC_OBS_EVENTS))
def test_event_in_ts_event_type_union(event_name: str):
    ts_events = _load_ts_event_types()
    assert event_name in ts_events, (
        f"Event '{event_name}' from EVENT_REGISTRY.md is missing from "
        f"packages/shared/events.ts EventType union. Add: | '{event_name}'"
    )
