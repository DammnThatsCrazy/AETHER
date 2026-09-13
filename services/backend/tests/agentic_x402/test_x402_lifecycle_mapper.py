"""Tests for X402LifecycleMapper — canonical event → repository routing."""

from __future__ import annotations

import pytest

from repositories.repos import (
    EconomicResourceRepository,
    FacilitatorRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
    AgentEconomicIdentityRepository,
    reset_in_memory_stores,
)
from services.x402.lifecycle_mapper import X402LifecycleMapper


@pytest.fixture(autouse=True)
def isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _make_mapper():
    return X402LifecycleMapper(
        payment_intents=PaymentIntentRepository(),
        settlements=SettlementEventRepository(),
        resources=EconomicResourceRepository(),
        facilitators=FacilitatorRepository(),
        identities=AgentEconomicIdentityRepository(),
    )


TENANT = "test-tenant"
AGENT = "agent-xyz"


@pytest.mark.asyncio
async def test_x402_payment_intent_created_writes_intent():
    mapper = _make_mapper()
    result = await mapper.handle_event(
        "x402_payment_intent_created",
        {
            "payment_intent_id": "pi-001",
            "agent_id": AGENT,
            "amount": "5.00",
            "currency": "USDC",
            "provider": "coinbase",
            "protocol": "x402",
        },
        TENANT,
    )
    assert result.get("status") in ("created", "exists", "inserted", "record_intent")
    rows = await PaymentIntentRepository().list_for_agent(AGENT, TENANT)
    assert any(r["intent_id"] == "pi-001" for r in rows)


@pytest.mark.asyncio
async def test_x402_payment_settled_writes_settlement():
    mapper = _make_mapper()
    # First create an intent
    await mapper.handle_event(
        "x402_payment_intent_created",
        {
            "payment_intent_id": "pi-002",
            "agent_id": AGENT,
            "amount": "3.00",
            "currency": "USDC",
            "provider": "stripe",
            "protocol": "x402",
        },
        TENANT,
    )
    # Now settle it
    result = await mapper.handle_event(
        "x402_payment_settled",
        {
            "settlement_event_id": "se-002",
            "payment_intent_id": "pi-002",
            "agent_id": AGENT,
            "amount": "3.00",
            "currency": "USDC",
            "provider": "stripe",
        },
        TENANT,
    )
    assert result is not None
    rows = await SettlementEventRepository().list_for_intent("pi-002", TENANT)
    assert any(r["settlement_event_id"] == "se-002" for r in rows)
    settled = [r for r in rows if r["settlement_event_id"] == "se-002"]
    assert settled[0]["status"] == "settled"


@pytest.mark.asyncio
async def test_x402_payment_failed_writes_failure():
    mapper = _make_mapper()
    await mapper.handle_event(
        "x402_payment_intent_created",
        {"payment_intent_id": "pi-003", "agent_id": AGENT, "amount": "1.00",
         "currency": "USDC", "provider": "test"},
        TENANT,
    )
    await mapper.handle_event(
        "x402_payment_failed",
        {"settlement_event_id": "se-003", "payment_intent_id": "pi-003",
         "agent_id": AGENT, "amount": "1.00", "currency": "USDC",
         "failure_reason": "insufficient_funds"},
        TENANT,
    )
    rows = await SettlementEventRepository().list_for_intent("pi-003", TENANT)
    failed = [r for r in rows if r["settlement_event_id"] == "se-003"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_x402_receipt_verified_updates_settlement():
    mapper = _make_mapper()
    await mapper.handle_event(
        "x402_payment_intent_created",
        {"payment_intent_id": "pi-004", "agent_id": AGENT, "amount": "2.00",
         "currency": "USDC", "provider": "test"},
        TENANT,
    )
    await mapper.handle_event(
        "x402_payment_settled",
        {"settlement_event_id": "se-004", "payment_intent_id": "pi-004",
         "agent_id": AGENT, "amount": "2.00", "currency": "USDC"},
        TENANT,
    )
    result = await mapper.handle_event(
        "x402_receipt_verified",
        {"settlement_event_id": "se-004", "receipt_id": "rcpt-001",
         "payment_intent_id": "pi-004"},
        TENANT,
    )
    assert result is not None


@pytest.mark.asyncio
async def test_x402_refund_writes_reversal():
    mapper = _make_mapper()
    await mapper.handle_event(
        "x402_payment_intent_created",
        {"payment_intent_id": "pi-005", "agent_id": AGENT, "amount": "7.00",
         "currency": "USDC", "provider": "test"},
        TENANT,
    )
    await mapper.handle_event(
        "x402_payment_settled",
        {"settlement_event_id": "se-005", "payment_intent_id": "pi-005",
         "agent_id": AGENT, "amount": "7.00", "currency": "USDC"},
        TENANT,
    )
    await mapper.handle_event(
        "x402_refund_or_reversal",
        {"settlement_event_id": "se-005r", "payment_intent_id": "pi-005",
         "agent_id": AGENT, "amount": "7.00", "currency": "USDC"},
        TENANT,
    )
    rows = await SettlementEventRepository().list_for_intent("pi-005", TENANT)
    reversal = [r for r in rows if r["status"] in ("reversed", "refunded")]
    assert len(reversal) >= 1


@pytest.mark.asyncio
async def test_x402_payment_legacy_normalizes():
    mapper = _make_mapper()
    result = await mapper.handle_event(
        "x402_payment",
        {
            "payment_intent_id": "pi-legacy",
            "settlement_event_id": "se-legacy",
            "agent_id": AGENT,
            "amount": "1.50",
            "currency": "USDC",
            "provider": "legacy-provider",
        },
        TENANT,
    )
    assert result is not None
    # Should have written a settlement record
    se_rows = await SettlementEventRepository().list_for_agent(AGENT, TENANT)
    assert len(se_rows) >= 1


@pytest.mark.asyncio
async def test_mapper_tenant_isolation():
    """Events for the same agent in two tenants must not cross-pollute."""
    mapper = _make_mapper()
    await mapper.handle_event(
        "x402_payment_intent_created",
        {"payment_intent_id": "pi-iso-a", "agent_id": AGENT, "amount": "4.00",
         "currency": "USDC", "provider": "iso"},
        "tenant-iso-a",
    )
    await mapper.handle_event(
        "x402_payment_intent_created",
        {"payment_intent_id": "pi-iso-b", "agent_id": AGENT, "amount": "5.00",
         "currency": "USDC", "provider": "iso"},
        "tenant-iso-b",
    )
    rows_a = await PaymentIntentRepository().list_for_agent(AGENT, "tenant-iso-a")
    rows_b = await PaymentIntentRepository().list_for_agent(AGENT, "tenant-iso-b")
    assert all(r["tenant_id"] == "tenant-iso-a" for r in rows_a)
    assert all(r["tenant_id"] == "tenant-iso-b" for r in rows_b)
