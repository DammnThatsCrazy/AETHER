"""
Parity tests: All 44 new entity types defined in ENTITY_MODEL.md must exist
as VertexType values in shared/graph/graph.py.

Parses graph.py as text to avoid the import chain (which requires cryptography
bindings not available in CI without the full dev install).
"""

from __future__ import annotations

import os
import re

import pytest

# Parse VertexType values directly from the source file to avoid import chain
_graph_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "shared", "graph", "graph.py"
))

with open(_graph_path) as _f:
    _graph_src = _f.read()

# Extract all string values assigned in VertexType class
# Matches lines like: SOME_NAME = "SomeValue"
_vertex_values: set[str] = set(re.findall(r'=\s*"([^"]+)"', _graph_src))

# ── Entity types expected from the Agentic Observability Layer ─────────────
# These match exactly what's documented in docs/source-of-truth/ENTITY_MODEL.md

EXPECTED_AGENTIC_VERTEX_TYPES = {
    # Agentic observation (MCP / tool / activity / risk)
    "ExternalAgent",
    "MCPConnection",
    "AgentToolObserved",
    "AgentPermissionSet",
    "AgentActivity",
    "AgentRiskSignal",
    # External agentic account / Robinhood-style
    "ExternalAgenticAccount",
    "ExternalBrokerageAccount",
    "AgentBudgetObserved",
    "TradingStrategyObserved",
    "TradeIntentObserved",
    "TradeOrderObserved",
    "TradeFillObserved",
    "TradeRejectionObserved",
    "PortfolioSnapshotObserved",
    "PositionSnapshotObserved",
    "AgentPerformanceSnapshotObserved",
    "AgentDisconnectObserved",
    "AgentNotificationObserved",
    # AgentMail-style communication
    "AgentInboxObserved",
    "AgentEmailAddressObserved",
    "AgentThreadObserved",
    "AgentMessageObserved",
    "AgentAttachmentObserved",
    "ExtractedEntityObserved",
    "OTPObservation",
    "InvoiceObservation",
    "ReceiptObservation",
    "CalendarIntentObserved",
    "SupportRoutingObserved",
    "MessageProviderObserved",
    # x402 / protocol
    "X402InteractionObserved",
    "X402ChallengeObserved",
    "X402PaymentRequirementObserved",
    "X402SignatureObserved",
    "X402FacilitatorObserved",
    "X402VerificationObserved",
    "X402SettlementObserved",
    "X402ResourceAccessObserved",
    "PaidResourceObserved",
    "ResourceProviderObserved",
    "ProtocolProviderObserved",
}


@pytest.mark.parametrize("entity_type", sorted(EXPECTED_AGENTIC_VERTEX_TYPES))
def test_entity_type_exists_as_vertex(entity_type: str):
    assert entity_type in _vertex_values, (
        f"Entity type '{entity_type}' from ENTITY_MODEL.md is missing from "
        f"shared/graph/graph.py VertexType class. "
        f"Add: <name> = \"{entity_type}\" to the VertexType class."
    )
