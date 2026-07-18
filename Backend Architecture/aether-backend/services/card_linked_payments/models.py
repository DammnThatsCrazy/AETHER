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
    # Fail-safe default for a region hint we do not recognise: treat it as the
    # MOST restrictive mode (strip user-level identifiers) rather than silently
    # granting unrestricted US_STANDARD behavior to an unknown jurisdiction.
    UNKNOWN_RESTRICTED = "UNKNOWN_RESTRICTED"


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


CARD_LINKED_SCHEMA_VERSION = "card_linked.v1"

# Amount buckets keep user-level volume filterable without exposing exact
# amounts on restricted surfaces.
_AMOUNT_BUCKETS = (
    ("0-10", 10.0), ("10-100", 100.0), ("100-1k", 1_000.0),
    ("1k-10k", 10_000.0), ("10k-100k", 100_000.0),
)


def amount_bucket(amount_usd: str | float | None) -> str | None:
    if amount_usd is None:
        return None
    try:
        value = float(amount_usd)
    except (TypeError, ValueError):
        return None
    for label, ceiling in _AMOUNT_BUCKETS:
        if value < ceiling:
            return label
    return "100k+"


def sdk_idempotency_key(tenant_id: str, source_event_id: str) -> str:
    return f"{tenant_id}:sdk:{source_event_id}:{CARD_LINKED_SCHEMA_VERSION}"


def paymentscan_idempotency_key(tenant_id: str, entity_type: str, entity_id: str,
                                metric_window: str, observed_at: str) -> str:
    return f"{tenant_id}:paymentscan:{entity_type}:{entity_id}:{metric_window}:{observed_at}"


def provider_idempotency_key(tenant_id: str, provider: str, provider_event_id: str) -> str:
    return f"{tenant_id}:{provider}:{provider_event_id}:{CARD_LINKED_SCHEMA_VERSION}"


def onchain_idempotency_key(tenant_id: str, chain: str, tx_hash: str,
                            log_index: str | int = "0") -> str:
    return f"{tenant_id}:onchain:{chain}:{tx_hash}:{log_index}:{CARD_LINKED_SCHEMA_VERSION}"


@dataclass(frozen=True)
class CardProgramObserved:
    """Catalog-backed card program observation (freshness-tracked)."""
    tenant_id: str
    card_program_id: str
    display_name: str
    source: CardLinkedSource
    status: str
    first_seen_at: str
    last_seen_at: str
    aliases: tuple[str, ...] = ()
    issuer_id: str | None = None
    payment_network: str | None = None


@dataclass(frozen=True)
class CardIssuerObserved:
    tenant_id: str
    issuer_id: str
    display_name: str
    source: CardLinkedSource
    status: str
    first_seen_at: str
    last_seen_at: str


@dataclass(frozen=True)
class CardAccountObserved:
    """A tenant-observed link between an actor and a card program.

    Never a card number — just the observed association plus provenance.
    """
    tenant_id: str
    card_account_id: str
    card_program_id: str
    actor_kind: str
    source: CardLinkedSource
    confidence: ObservationConfidence
    first_seen_at: str
    last_seen_at: str
    canonical_entity_id: str | None = None
    user_id: str | None = None
    wallet_address_hash: str | None = None
    issuer_id: str | None = None
    payment_network: str | None = None


@dataclass(frozen=True)
class CardProviderHealth:
    tenant_id: str
    source: str
    last_event_at: str | None
    last_sync_at: str | None
    event_count_24h: int = 0
    error_count_24h: int = 0
    status: str = "unknown"  # healthy | degraded | stale | unknown


@dataclass(frozen=True)
class CardReconciliationRecord:
    tenant_id: str
    reconciliation_id: str
    flow_ids: tuple[str, ...]
    state: str  # matched | conflict | stale
    matched_on: str  # wallet_hash_program_window | provider_ref | none
    created_at: str
    notes: str = ""
