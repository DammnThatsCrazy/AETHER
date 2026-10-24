"""Journey to commerce evidence uses explicit refs and preserves source facts."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.measurement.repositories import (  # noqa: E402
    activity_repo,
    journey_repo,
    journey_step_repo,
)
from value.commerce import order_payment_reconciliation  # noqa: E402
from value.economic.journey_operation_evidence import (  # noqa: E402
    _commerce_payment_facts,
    campaign_commerce_operation_evidence,
    entity_commerce_operation_evidence,
    journey_commerce_operation_evidence,
)


def _ledger_record(reference: str, *, payments: list[dict[str, Any]]) -> dict[str, Any]:
    first_order_revision = {
        "provider": "shopify",
        "providerOrderId": f"{reference}-order",
        "amount": "10.00",
        "currency": "USD",
        "revisionId": f"{reference}-revision",
        "sourceRevisionAt": "2026-10-17T10:00:00Z",
        "occurredAt": "2026-10-17T10:00:00Z",
        "observedAt": "2026-10-17T10:01:00Z",
    }
    second_order_revision = {
        **first_order_revision,
        "amount": "11.00",
        "revisionId": f"{reference}-revision-2",
        "sourceRevisionAt": "2026-10-17T11:00:00Z",
        "occurredAt": "2026-10-17T11:00:00Z",
        "observedAt": "2026-10-17T11:01:00Z",
    }
    return {
        "tenantId": "tenant-a",
        "commerceOrderRef": reference,
        "state": "multiple_payments" if len(payments) > 1 else "matched",
        "createdAt": "2026-10-17T10:00:00Z",
        "updatedAt": "2026-10-18T12:01:00Z",
        "order": second_order_revision,
        "orderRevisions": [first_order_revision, second_order_revision],
        "payments": {
            f"{payment['provider']}:{payment['providerPaymentId']}": payment for payment in payments
        },
        "paymentObservations": payments,
        "adjustments": {
            "stripe:refund-1": {
                "provider": "stripe",
                "adjustmentId": "refund-1",
                "adjustmentType": "refund",
                "reversesPaymentId": "pay-1",
                "amount": "2.00",
                "currency": "USD",
                "occurredAt": "2026-10-18T10:00:00Z",
                "observedAt": "2026-10-18T10:01:00Z",
            }
        },
        "adjustmentObservations": [
            {
                "provider": "stripe",
                "adjustmentId": "refund-1",
                "adjustmentType": "refund",
                "reversesPaymentId": "pay-1",
                "amount": "2.00",
                "currency": "USD",
                "occurredAt": "2026-10-18T10:00:00Z",
                "observedAt": "2026-10-18T10:01:00Z",
            }
        ],
        "settlements": {
            "stripe:settlement-1": {
                "provider": "stripe",
                "providerSettlementId": "settlement-1",
                "status": "settled",
                "amount": "8.00",
                "currency": "USD",
                "settlesPaymentRefs": [{"provider": "stripe", "providerPaymentId": "pay-1"}],
                "occurredAt": "2026-10-18T12:00:00Z",
                "observedAt": "2026-10-18T12:01:00Z",
            }
        },
        "settlementObservations": [
            {
                "provider": "stripe",
                "providerSettlementId": "settlement-1",
                "status": "settled",
                "amount": "8.00",
                "currency": "USD",
                "settlesPaymentRefs": [{"provider": "stripe", "providerPaymentId": "pay-1"}],
                "occurredAt": "2026-10-18T12:00:00Z",
                "observedAt": "2026-10-18T12:01:00Z",
            }
        ],
    }


@pytest.mark.asyncio
async def test_journey_commerce_evidence_preserves_exact_source_payment_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeJourneyRepository:
        async def get_current(self, tenant_id: str, journey_id: str):
            assert (tenant_id, journey_id) == ("tenant-a", "journey-1")
            return {"journey_version_id": "version-1"}

    class FakeJourneyStepRepository:
        async def list_by_version(
            self, tenant_id: str, version_id: str, *, limit: int, cursor=None
        ):
            assert (tenant_id, version_id) == ("tenant-a", "version-1")
            assert cursor is None
            return [
                {
                    "step_position": "1",
                    "evidence_summary": {
                        "commerce_order_ref": "order:exact-1",
                        "commerce_order_refs": ["order:exact-1"],
                        "untrusted_order_id": "order:must-not-join",
                    },
                }
            ]

    payment_rows = [
        {
            "provider": "stripe",
            "providerPaymentId": f"pay-{index}",
            "amount": "10.00",
            "currency": "USD" if index == 1 else "EUR",
            "status": "completed",
            "occurredAt": f"2026-10-17T10:0{index}:00Z",
            "observedAt": f"2026-10-17T10:1{index}:00Z",
        }
        for index in (1, 2)
    ]
    record = _ledger_record("order:exact-1", payments=payment_rows)
    enriched_payment = {
        **payment_rows[0],
        "paymentRail": "coinbase",
        "flowType": "crypto_onramp",
        "sourceAmount": "10.00",
        "sourceAsset": "USD",
        "destinationAmount": "0.005",
        "destinationAsset": "ETH",
        "destinationChain": "ethereum",
        "txHash": "0xpay-1-hash",
        "observedAt": "2026-10-17T10:15:00Z",
    }
    record["paymentObservations"] = [payment_rows[0], enriched_payment, payment_rows[1]]
    record["state"] = "conflict"
    record["conflictReason"] = "provider_payment_id_reused_with_divergent_evidence"
    calls: list[tuple[str, str, str]] = []

    class FakeLedger:
        async def get_as_of(self, tenant_id: str, reference: str, as_of: str):
            calls.append(("as_of", tenant_id, reference))
            assert as_of == "2026-10-17T11:00:00Z"
            return record

        async def get(self, tenant_id: str, reference: str):
            calls.append(("current", tenant_id, reference))
            return record

    monkeypatch.setattr(journey_repo, "JourneyRepository", FakeJourneyRepository)
    monkeypatch.setattr(journey_step_repo, "JourneyStepRepository", FakeJourneyStepRepository)
    monkeypatch.setattr(order_payment_reconciliation, "CommerceOrderPaymentLedger", FakeLedger)

    result = await journey_commerce_operation_evidence(
        "tenant-a", "journey-1", as_of="2026-10-17T11:00:00Z"
    )

    assert calls == [("as_of", "tenant-a", "order:exact-1")]
    assert result["join_basis"] == "explicit_journey_step_commerce_order_ref"
    assert result["amounts_included"] is True
    assert result["operation_link_amounts_included"] is False
    assert result["facts_are_aggregated"] is False
    assert len(result["operation_links"]) == 1
    facts = result["payment_facts"]
    assert [fact["kind"] for fact in facts] == [
        "order",
        "order",
        "payment",
        "payment",
        "refund",
        "settlement",
    ]
    assert [fact["amount"] for fact in facts] == [
        "10.00",
        "11.00",
        "10.00",
        "10.00",
        "2.00",
        "8.00",
    ]
    assert all(fact["amountUsd"] is not None for fact in facts if fact["currency"] == "USD")
    assert facts[3]["currency"] == "EUR"
    assert facts[3]["amountUsd"] is None
    assert facts[3]["normalizationState"] == "not_normalized"
    assert all(fact["reconciliationState"] == "conflict" for fact in facts)
    assert all(
        fact["conflictReason"] == "provider_payment_id_reused_with_divergent_evidence"
        for fact in facts
    )
    assert [fact["revisionId"] for fact in facts[:2]] == [
        "order:exact-1-revision",
        "order:exact-1-revision-2",
    ]
    assert facts[0]["sourceRevisionAt"] == "2026-10-17T10:00:00Z"
    assert facts[0]["evidence"][0]["id"] == "order:exact-1-revision"
    assert facts[2]["lifecycleState"] == "completed"
    assert facts[4]["lifecycleState"] == "refund"
    assert facts[4]["reversesPaymentId"] == "pay-1"
    assert facts[5]["lifecycleState"] == "settled"
    assert facts[5]["settlesPaymentRefs"] == [{"provider": "stripe", "providerPaymentId": "pay-1"}]
    assert facts[2]["observedAt"] == enriched_payment["observedAt"]
    assert facts[2]["evidence"][0]["id"] == "pay-1"
    assert facts[2]["evidence"][0]["observedAt"] == payment_rows[0]["observedAt"]
    assert facts[2]["paymentRail"] == "coinbase"
    assert facts[2]["flowType"] == "crypto_onramp"
    assert facts[2]["destinationAmount"] == "0.005"
    assert facts[2]["destinationAsset"] == "ETH"
    assert facts[2]["destinationChain"] == "ethereum"
    assert facts[2]["evidence"][1]["id"] == "0xpay-1-hash"
    assert facts[2]["evidence"][1]["type"] == "transaction"
    assert all(fact["ledgerUpdatedAt"] == "2026-10-18T12:01:00Z" for fact in facts)
    assert all(fact["joinBasis"] == result["join_basis"] for fact in facts)
    assert "total" not in {key.lower() for fact in facts for key in fact}


def test_compatible_payment_enrichment_emits_one_source_fact() -> None:
    payment = {
        "provider": "coinbase",
        "providerPaymentId": "payment-1",
        "amount": "100.00",
        "currency": "USD",
        "status": "completed",
        "occurredAt": "2026-10-17T10:00:00Z",
        "observedAt": "2026-10-17T10:01:00Z",
    }
    record = {
        "commerceOrderRef": "order:exact-1",
        "payments": {"coinbase:payment-1": payment},
        "paymentObservations": [
            payment,
            {
                **payment,
                "paymentRail": "coinbase",
                "flowType": "crypto_onramp",
                "destinationAmount": "0.05",
                "destinationAsset": "ETH",
                "destinationChain": "ethereum",
                "txHash": "0xabc123",
                "observedAt": "2026-10-17T10:02:00Z",
            },
        ],
    }

    payment_facts = [
        fact
        for fact in _commerce_payment_facts(record, as_of=None)
        if fact["kind"] == "payment"
    ]

    assert len(payment_facts) == 1
    assert payment_facts[0]["paymentRail"] == "coinbase"
    assert payment_facts[0]["destinationAsset"] == "ETH"
    assert payment_facts[0]["observedAt"] == "2026-10-17T10:02:00Z"
    assert [ref["id"] for ref in payment_facts[0]["evidence"]] == [
        "payment-1",
        "0xabc123",
    ]


@pytest.mark.asyncio
async def test_missing_exact_commerce_record_is_reported_as_partial(monkeypatch) -> None:
    class FakeJourneyRepository:
        async def get_current(self, tenant_id: str, journey_id: str):
            return {"journey_version_id": "version-1"}

    class FakeJourneyStepRepository:
        async def list_by_version(
            self, tenant_id: str, version_id: str, *, limit: int, cursor=None
        ):
            return [
                {
                    "step_position": "1",
                    "evidence_summary": {"commerce_order_ref": "order:unrecorded"},
                }
            ]

    class FakeLedger:
        async def get(self, tenant_id: str, reference: str):
            return None

    monkeypatch.setattr(journey_repo, "JourneyRepository", FakeJourneyRepository)
    monkeypatch.setattr(journey_step_repo, "JourneyStepRepository", FakeJourneyStepRepository)
    monkeypatch.setattr(order_payment_reconciliation, "CommerceOrderPaymentLedger", FakeLedger)

    result = await journey_commerce_operation_evidence("tenant-a", "journey-1")
    assert result["payment_facts"] == []
    assert result["operation_links"] == []
    assert result["unresolved_order_references"] == 1
    assert result["evidence_truncated"] is True


@pytest.mark.asyncio
async def test_campaign_commerce_evidence_joins_only_same_tenant_canonical_activity_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeActivityRepository:
        async def list_commerce_by_campaign(
            self, tenant_id: str, campaign_id: str, *, limit: int, as_of: str | None
        ):
            assert (tenant_id, campaign_id) == ("tenant-a", "campaign-a")
            assert limit == 1_001
            assert as_of == "2026-10-17T11:00:00Z"
            return [
                {
                    "tenant_id": "tenant-a",
                    "campaign_id": "campaign-a",
                    "activity_family": "commerce",
                    "activity_status": "confirmed",
                    "activity_id": "activity-campaign-payment",
                    "commerce_order_ref": "order:campaign-1",
                    "silver_table": "silver_revenue_facts",
                    "server_received_at": "2026-10-17T10:30:00Z",
                },
                {
                    "tenant_id": "tenant-b",
                    "campaign_id": "campaign-a",
                    "activity_family": "commerce",
                    "activity_status": "confirmed",
                    "activity_id": "cross-tenant",
                    "commerce_order_ref": "order:must-not-read",
                },
                {
                    "tenant_id": "tenant-a",
                    "campaign_id": "another-campaign",
                    "activity_family": "commerce",
                    "activity_status": "confirmed",
                    "activity_id": "wrong-campaign",
                    "commerce_order_ref": "order:must-not-read-either",
                },
            ]

    payment = {
        "provider": "stripe",
        "providerPaymentId": "payment-campaign-1",
        "amount": "23.40",
        "currency": "USD",
        "status": "completed",
        "occurredAt": "2026-10-17T10:00:00Z",
        "observedAt": "2026-10-17T10:01:00Z",
    }
    ledger_record = _ledger_record("order:campaign-1", payments=[payment])
    calls: list[tuple[str, str, str]] = []

    class FakeLedger:
        async def get_as_of(self, tenant_id: str, reference: str, as_of: str):
            calls.append((tenant_id, reference, as_of))
            return ledger_record

        async def get(self, tenant_id: str, reference: str):
            raise AssertionError("as-of request must use the as-of ledger read")

    monkeypatch.setattr(activity_repo, "ActivityRepository", FakeActivityRepository)
    monkeypatch.setattr(order_payment_reconciliation, "CommerceOrderPaymentLedger", FakeLedger)

    result = await campaign_commerce_operation_evidence(
        "tenant-a",
        "campaign-a",
        as_of="2026-10-17T11:00:00Z",
    )

    assert calls == [("tenant-a", "order:campaign-1", "2026-10-17T11:00:00Z")]
    assert result["join_basis"] == (
        "explicit_campaign_scoped_canonical_activity_commerce_order_ref"
    )
    assert result["facts_are_aggregated"] is False
    assert len(result["association_evidence"]) == 1
    assert result["association_evidence"][0]["activityId"] == "activity-campaign-payment"
    payment_fact = next(fact for fact in result["payment_facts"] if fact["kind"] == "payment")
    assert payment_fact["commerceOrderRef"] == "order:campaign-1"
    assert payment_fact["joinBasis"] == result["join_basis"]
    assert payment_fact["amount"] == "23.40"


@pytest.mark.asyncio
async def test_entity_commerce_evidence_uses_exact_canonical_profile_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeActivityRepository:
        async def list_commerce_by_profile(
            self, tenant_id: str, profile_id: str, *, limit: int, as_of: str | None
        ):
            assert (tenant_id, profile_id) == ("tenant-a", "entity-a")
            assert limit == 1_001
            assert as_of is None
            return [
                {
                    "tenant_id": "tenant-a",
                    "profile_id": "entity-a",
                    "activity_family": "commerce",
                    "activity_status": "confirmed",
                    "activity_id": "activity-entity-payment",
                    "commerce_order_ref": "order:entity-1",
                    "silver_table": "silver_revenue_facts",
                    "server_received_at": "2026-10-17T10:30:00Z",
                }
            ]

    ledger_record = _ledger_record(
        "order:entity-1",
        payments=[
            {
                "provider": "stripe",
                "providerPaymentId": "payment-entity-1",
                "amount": "19.00",
                "currency": "USD",
                "status": "completed",
                "occurredAt": "2026-10-17T10:00:00Z",
                "observedAt": "2026-10-17T10:01:00Z",
            }
        ],
    )

    class FakeLedger:
        async def get(self, tenant_id: str, reference: str):
            assert (tenant_id, reference) == ("tenant-a", "order:entity-1")
            return ledger_record

    monkeypatch.setattr(activity_repo, "ActivityRepository", FakeActivityRepository)
    monkeypatch.setattr(order_payment_reconciliation, "CommerceOrderPaymentLedger", FakeLedger)

    result = await entity_commerce_operation_evidence("tenant-a", "entity-a")

    payment_fact = next(fact for fact in result["payment_facts"] if fact["kind"] == "payment")
    assert result["entity_id"] == "entity-a"
    assert result["join_basis"] == ("explicit_canonical_profile_scoped_activity_commerce_order_ref")
    assert result["association_evidence"][0]["subjectId"] == "entity-a"
    assert payment_fact["commerceOrderRef"] == "order:entity-1"
    assert payment_fact["amount"] == "19.00"


@pytest.mark.asyncio
async def test_invalid_commerce_reference_marks_subject_evidence_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeActivityRepository:
        async def list_commerce_by_campaign(
            self, tenant_id: str, campaign_id: str, *, limit: int, as_of: str | None
        ):
            return [
                {
                    "tenant_id": tenant_id,
                    "campaign_id": campaign_id,
                    "activity_family": "commerce",
                    "activity_status": "confirmed",
                    "activity_id": "activity-invalid-reference",
                    "commerce_order_ref": "order:invalid\x00reference",
                }
            ]

    class UnexpectedLedger:
        async def get(self, tenant_id: str, reference: str):
            raise AssertionError("invalid references must not reach the ledger")

    monkeypatch.setattr(activity_repo, "ActivityRepository", FakeActivityRepository)
    monkeypatch.setattr(
        order_payment_reconciliation, "CommerceOrderPaymentLedger", UnexpectedLedger
    )

    result = await campaign_commerce_operation_evidence("tenant-a", "campaign-a")

    assert result["payment_facts"] == []
    assert result["invalid_order_reference_count"] == 1
    assert result["evidence_truncated"] is True


@pytest.mark.asyncio
async def test_activity_commerce_campaign_reader_is_tenant_status_and_as_of_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "tenant_id": "tenant-a",
            "campaign_id": "campaign-a",
            "activity_family": "commerce",
            "activity_status": "confirmed",
            "activity_id": "visible",
            "commerce_order_ref": "order:visible",
            "server_received_at": "2026-10-17T10:00:00Z",
        },
        {
            "tenant_id": "tenant-a",
            "campaign_id": "campaign-a",
            "activity_family": "commerce",
            "activity_status": "confirmed",
            "activity_id": "future",
            "commerce_order_ref": "order:future",
            "server_received_at": "2026-10-17T12:00:00Z",
        },
        {
            "tenant_id": "tenant-a",
            "campaign_id": "campaign-a",
            "activity_family": "commerce",
            "activity_status": "consent_restricted",
            "activity_id": "restricted",
            "commerce_order_ref": "order:restricted",
            "server_received_at": "2026-10-17T09:00:00Z",
        },
        {
            "tenant_id": "tenant-b",
            "campaign_id": "campaign-a",
            "activity_family": "commerce",
            "activity_status": "confirmed",
            "activity_id": "other-tenant",
            "commerce_order_ref": "order:other-tenant",
            "server_received_at": "2026-10-17T09:00:00Z",
        },
    ]
    local_rows = {str(index): row for index, row in enumerate(rows)}
    monkeypatch.setattr(activity_repo, "_local_store", local_rows)
    monkeypatch.setattr(
        activity_repo.ActivityRepository,
        "_pool",
        lambda self: _no_pool(),
    )

    result = await activity_repo.ActivityRepository().list_commerce_by_campaign(
        "tenant-a",
        "campaign-a",
        as_of="2026-10-17T11:00:00Z",
    )

    assert [row["activity_id"] for row in result] == ["visible"]


async def _no_pool():
    return None
