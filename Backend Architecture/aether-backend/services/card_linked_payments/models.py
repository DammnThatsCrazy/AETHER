"""Card-linked payment rail observability V1 models and privacy guards.

Observation-first semantics only: this module represents normalized facts about
card-linked activity and benchmarks. It never stores PAN/CVV/raw KYC/bank data
and never treats PaymentScan as deterministic user-level truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal


class CardActivityBasis(StrEnum):
    TOPUP = "topup"
    FUNDING = "funding"
    SPEND = "spend"
    SETTLEMENT = "settlement"
    CLEARING = "clearing"
    REFUND = "refund"
    REVERSAL = "reversal"
    MIXED = "mixed"
    BENCHMARK_ONLY = "benchmark_only"
    UNKNOWN = "unknown"


class CardLinkedSource(StrEnum):
    PAYMENTSCAN = "paymentscan"
    SDK = "sdk"
    ONCHAIN_OBSERVER = "onchain_observer"
    PROVIDER_WEBHOOK = "provider_webhook"
    ISSUER_API = "issuer_api"
    TENANT_IMPORT = "tenant_import"
    MANUAL_SEED = "manual_seed"


class ObservationConfidence(StrEnum):
    WEAK = "weak"
    PROBABLE = "probable"
    STRONG = "strong"
    DETERMINISTIC = "deterministic"


class RegionPolicyMode(StrEnum):
    US_STANDARD = "US_STANDARD"
    EU_RESTRICTED = "EU_RESTRICTED"
    UK_RESTRICTED = "UK_RESTRICTED"
    APAC_RESTRICTED = "APAC_RESTRICTED"
    GLOBAL_AGGREGATE_ONLY = "GLOBAL_AGGREGATE_ONLY"


BLOCKED_CARD_LINKED_FIELDS = {
    "pan", "cvv", "raw_kyc_document", "full_bank_account", "routing_number",
    "provider_secret", "authorization", "authorization_header", "private_api_key",
    "passport_image", "driver_license_image", "national_id_image",
    "raw_cardholder_identity_documents", "full_card_number",
}

CARD_LINKED_FIELD_CLASSIFICATION = {
    "tx_hash": "public_onchain",
    "wallet_address_hash": "pseudonymous_identifier",
    "provider_customer_ref": "restricted_identifier",
    "card_program_id": "catalog_dimension",
    "issuer_id": "catalog_dimension",
    "payment_network": "catalog_dimension",
    "amount_usd": "financial_behavior",
    "basis": "financial_behavior_metadata",
    "campaign_id": "attribution_metadata",
    "journey_id": "behavioral_metadata",
    **{field: "blocked" for field in BLOCKED_CARD_LINKED_FIELDS},
}


def reject_blocked_fields(payload: dict[str, Any]) -> None:
    present = sorted(field for field in BLOCKED_CARD_LINKED_FIELDS if payload.get(field) is not None)
    if present:
        raise ValueError(f"Blocked card-linked fields present: {', '.join(present)}")


def redact_blocked_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: ("[REDACTED_BLOCKED]" if key in BLOCKED_CARD_LINKED_FIELDS else value) for key, value in payload.items()}


@dataclass(frozen=True)
class CardLinkedFlowObserved:
    id: str
    tenant_id: str
    actor_kind: Literal["human", "agent", "org", "wallet", "service", "system"]
    rail: Literal["card", "onchain", "bank_transfer", "x402", "unknown"]
    basis: CardActivityBasis
    source: CardLinkedSource
    confidence: ObservationConfidence
    evidence_refs: list[str]
    reconciliation_state: Literal["sdk_only", "provider_only", "onchain_only", "benchmark_only", "matched", "stale", "conflict", "ignored_duplicate"]
    occurred_at: str
    observed_at: str
    created_at: str
    updated_at: str
    canonical_entity_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    org_id: str | None = None
    wallet_address_hash: str | None = None
    card_program_id: str | None = None
    issuer_id: str | None = None
    payment_network: Literal["visa", "mastercard", "unknown"] | None = None
    chain: str | None = None
    asset: str | None = None
    amount_usd: str | None = None
    amount_native: str | None = None
    amount_bucket: str | None = None
    campaign_id: str | None = None
    journey_id: str | None = None
    session_id: str | None = None
    device_id: str | None = None
    region_policy: RegionPolicyMode | None = None
    consent_snapshot: dict[str, bool] | None = None

    @classmethod
    def benchmark(cls, *, tenant_id: str, catalog_entity_id: str, observed_at: str | None = None) -> "CardLinkedFlowObserved":
        ts = observed_at or datetime.now(timezone.utc).isoformat()
        return cls(
            id=f"{tenant_id}:paymentscan:{catalog_entity_id}:{ts}", tenant_id=tenant_id,
            actor_kind="system", rail="unknown", basis=CardActivityBasis.BENCHMARK_ONLY,
            source=CardLinkedSource.PAYMENTSCAN, confidence=ObservationConfidence.WEAK,
            evidence_refs=[catalog_entity_id], reconciliation_state="benchmark_only",
            occurred_at=ts, observed_at=ts, created_at=ts, updated_at=ts,
        )


@dataclass(frozen=True)
class CardBenchmarkObservation:
    tenant_id: str
    catalog_entity_id: str
    metric_name: str
    metric_window: str
    basis: CardActivityBasis = CardActivityBasis.BENCHMARK_ONLY
    source: CardLinkedSource = CardLinkedSource.PAYMENTSCAN
    confidence: ObservationConfidence = ObservationConfidence.WEAK
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
