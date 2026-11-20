"""x402 settlement observer: the chain, not the report, decides settlement.

Aether is observation-only (ADR-012). A tenant's server reports an x402
exchange; the observer checks the payment on-chain and records settled, failed,
pending or not observable. These tests pin each state, the deterministic
observation identity, the hand-off through the authoritative lifecycle
consumer into the payment repositories, and that producers of the retired
commerce control plane are no longer accepted live.
"""

from __future__ import annotations

import pytest

from ingestion.ingestion import lifecycle_worker
from repositories.repos import (
    PaymentIntentRepository,
    SettlementEventRepository,
    reset_in_memory_stores,
)
from shared.events.events import Event, Topic
from value.x402 import settlement_observer
from value.x402.commerce_models import PaymentReceipt
from value.x402.models import CapturedX402Transaction, PaymentProof, PaymentTerms
from value.x402.provenance import (
    AUTHORITATIVE_X402_SOURCES,
    HISTORICAL_X402_SOURCES,
    is_server_authoritative_x402_metadata,
)

TENANT = "tenant-observer"
TX_HASH = "0x" + "ab" * 32
PAYER = "0x" + "11" * 20
RECIPIENT = "0x" + "22" * 20


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    reset_in_memory_stores()

    async def sandbox(_tenant_id: str) -> str:
        return "sandbox"

    monkeypatch.setattr(settlement_observer, "resolve_x402_environment", sandbox)
    yield
    reset_in_memory_stores()


def _capture(*, token: str = "USDC", chain: str = "eip155:8453", proof: bool = True) -> CapturedX402Transaction:
    return CapturedX402Transaction(
        capture_id="cap-1",
        payer_agent_id="agent-reported",
        payee_service_id="svc-1",
        terms=PaymentTerms(amount=1.25, token=token, chain=chain, recipient=RECIPIENT),
        proof=PaymentProof(tx_hash=TX_HASH, payer=PAYER, chain=chain, amount=1.25, token=token) if proof else None,
        request_url="https://api.example/resource",
    )


class _Engine:
    """Stands in for the on-chain verifier and records what it was asked."""

    def __init__(self, *, verified: bool, verdict: str):
        self.verified = verified
        self.verdict = verdict
        self.calls: list[tuple] = []

    async def verify(self, tenant_id, authorization, tx_hash, prefer_facilitator=True):
        self.calls.append((tenant_id, authorization, tx_hash, prefer_facilitator))
        return PaymentReceipt(
            receipt_id="rcpt-1",
            tenant_id=tenant_id,
            authorization_id=authorization.authorization_id,
            challenge_id=authorization.challenge_id,
            tx_hash=tx_hash,
            chain=authorization.chain,
            asset_symbol=authorization.asset_symbol,
            amount_usd=authorization.amount_usd,
            payer=authorization.payer,
            recipient=authorization.recipient,
            verified=self.verified,
            verification_verdict=self.verdict,
            verified_at="2026-11-20T10:00:00+00:00" if self.verified else None,
        )


class _Producer:
    def __init__(self):
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_report_without_proof_makes_no_settlement_claim():
    engine, producer = _Engine(verified=True, verdict="verified"), _Producer()
    result = await settlement_observer.observe_settlement(
        TENANT, _capture(proof=False), engine=engine, producer=producer
    )
    assert result == {"state": "not_observable", "reason": "no_payment_proof"}
    assert engine.calls == [] and producer.events == []


@pytest.mark.asyncio
async def test_unsupported_asset_is_not_observable_not_failed():
    engine, producer = _Engine(verified=False, verdict="verification_failed"), _Producer()
    result = await settlement_observer.observe_settlement(
        TENANT, _capture(token="DAI"), engine=engine, producer=producer
    )
    assert result["state"] == "not_observable"
    assert result["reason"] == "unsupported_asset_or_chain"
    assert engine.calls == [] and producer.events == []


@pytest.mark.asyncio
async def test_verified_payment_is_settled_by_the_observer_from_report_facts():
    engine, producer = _Engine(verified=True, verdict="verified"), _Producer()
    result = await settlement_observer.observe_settlement(
        TENANT, _capture(), engine=engine, producer=producer
    )
    assert result["state"] == "settled"
    expected_id = settlement_observer.observation_id_for(TENANT, "eip155:8453", TX_HASH)
    assert result["observation_id"] == expected_id
    (_, authorization, tx_hash, prefer_facilitator), = engine.calls
    assert tx_hash == TX_HASH and prefer_facilitator is False
    assert authorization.payer == PAYER and authorization.recipient == RECIPIENT
    assert authorization.amount_usd == 1.25 and authorization.environment == "sandbox"
    (event,) = producer.events
    assert event.topic == Topic.COMMERCE_SETTLEMENT_COMPLETED
    assert event.source_service == settlement_observer.OBSERVER_SOURCE
    assert event.payload["observation_id"] == expected_id
    assert event.payload["agent_ref_source"] == "capture_reported"


@pytest.mark.asyncio
async def test_terminal_negative_verdict_is_failed():
    engine, producer = _Engine(verified=False, verdict="payer_mismatch"), _Producer()
    result = await settlement_observer.observe_settlement(
        TENANT, _capture(), engine=engine, producer=producer
    )
    assert result["state"] == "failed"
    (event,) = producer.events
    assert event.topic == Topic.COMMERCE_SETTLEMENT_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["not_finalized", "verification_unavailable"])
async def test_retryable_verdict_stays_pending_and_records_nothing_terminal(verdict):
    engine, producer = _Engine(verified=False, verdict=verdict), _Producer()
    result = await settlement_observer.observe_settlement(
        TENANT, _capture(), engine=engine, producer=producer
    )
    assert result["state"] == "pending"
    assert producer.events == []


def test_observation_identity_is_deterministic_and_tenant_scoped():
    a = settlement_observer.observation_id_for(TENANT, "eip155:8453", TX_HASH)
    assert a == settlement_observer.observation_id_for(TENANT, "eip155:8453", TX_HASH.upper().replace("0X", "0x"))
    assert a != settlement_observer.observation_id_for("other-tenant", "eip155:8453", TX_HASH)


@pytest.mark.asyncio
async def test_observer_settlement_projects_idempotently_into_payment_repositories():
    engine, producer = _Engine(verified=True, verdict="verified"), _Producer()
    await settlement_observer.observe_settlement(TENANT, _capture(), engine=engine, producer=producer)
    (event,) = producer.events
    await lifecycle_worker.project_authoritative_x402_lifecycle(event)
    await lifecycle_worker.project_authoritative_x402_lifecycle(event)

    intent_id = event.payload["observation_id"]
    intent = await PaymentIntentRepository().find_for_tenant(intent_id, TENANT)
    assert intent is not None
    settlements = await SettlementEventRepository().list_for_intent(intent_id, TENANT)
    assert len(settlements) == 1
    assert settlements[0]["status"] == "settled"
    assert settlements[0]["tx_hash"] == TX_HASH
    assert settlements[0]["currency"] == "USDC"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic,source",
    [
        (Topic.COMMERCE_SETTLEMENT_COMPLETED, "x402.settlement"),
        (Topic.COMMERCE_SETTLEMENT_COMPLETED, "public-sdk"),
        (Topic.COMMERCE_ACCESS_GRANTED, "x402.control_plane"),
        (Topic.COMMERCE_PAYMENT_SUBMITTED, "x402.control_plane"),
    ],
)
async def test_retired_control_plane_producers_are_not_projected_live(topic, source):
    event = Event(
        topic=topic,
        tenant_id=TENANT,
        source_service=source,
        payload={"observation_id": "x402obs_forged", "tx_hash": TX_HASH, "amount": "9", "asset_symbol": "USDC"},
    )
    await lifecycle_worker.project_authoritative_x402_lifecycle(event)
    assert await PaymentIntentRepository().find_for_tenant("x402obs_forged", TENANT) is None


def test_only_the_settlement_observer_is_a_live_authority():
    assert {svc for svc, _ in AUTHORITATIVE_X402_SOURCES.values()} == {
        settlement_observer.OBSERVER_SOURCE
    }


def test_records_written_by_the_retired_control_plane_stay_server_observed():
    for topic, (service, _stage) in HISTORICAL_X402_SOURCES.items():
        assert is_server_authoritative_x402_metadata(
            {"evidence_status": "server_observed", "source_topic": topic, "source_service": service}
        )
    assert not is_server_authoritative_x402_metadata(
        {"evidence_status": "server_observed", "source_topic": "aether.commerce.settlement.completed",
         "source_service": "public-sdk"}
    )
