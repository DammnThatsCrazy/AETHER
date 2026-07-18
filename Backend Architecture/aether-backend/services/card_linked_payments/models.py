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
    AUTHORIZATION = "authorization"  # pre-settlement hold — never settled spend
    SETTLEMENT = "settlement"
    CLEARING = "clearing"
    REFUND = "refund"
    REVERSAL = "reversal"
    MIXED = "mixed"
    BENCHMARK_ONLY = "benchmark_only"
    UNKNOWN = "unknown"


class EvidenceStrength(StrEnum):
    """How strongly a card-linked observation is evidenced.

    Ordering (weakest → strongest): ``unconfirmed`` < ``benchmark`` <
    ``self_reported`` < ``sdk_reported`` < ``onchain_observed`` <
    ``provider_confirmed``. Only genuine provider/issuer evidence may be labeled
    ``provider_confirmed``; SDK/self-reported/on-chain observations are never
    promoted to provider-confirmed spend (see
    :func:`assert_evidence_not_overclaimed`).
    """

    PROVIDER_CONFIRMED = "provider_confirmed"
    ONCHAIN_OBSERVED = "onchain_observed"
    SDK_REPORTED = "sdk_reported"
    SELF_REPORTED = "self_reported"       # tenant import / manual seed
    BENCHMARK = "benchmark"               # PaymentScan market intelligence
    UNCONFIRMED = "unconfirmed"


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


# ── evidence-strength labeling ────────────────────────────────────────────────
# Only these sources may ever be labeled ``provider_confirmed``. Everything else
# (SDK telemetry, tenant imports, on-chain observations, PaymentScan benchmarks)
# is a weaker form of evidence and must NEVER be promoted to provider-confirmed
# spend without independent provider evidence.
_PROVIDER_CONFIRMED_SOURCES = frozenset({"provider_webhook", "issuer_api"})

_SOURCE_EVIDENCE_STRENGTH = {
    "provider_webhook": EvidenceStrength.PROVIDER_CONFIRMED,
    "issuer_api": EvidenceStrength.PROVIDER_CONFIRMED,
    "onchain_observer": EvidenceStrength.ONCHAIN_OBSERVED,
    "sdk": EvidenceStrength.SDK_REPORTED,
    "tenant_import": EvidenceStrength.SELF_REPORTED,
    "manual_seed": EvidenceStrength.SELF_REPORTED,
    "paymentscan": EvidenceStrength.BENCHMARK,
}


class EvidenceOverclaimError(ValueError):
    """Raised when a non-provider source is labeled provider-confirmed spend."""


def classify_evidence_strength(source: str | None,
                               reconciliation_state: str | None = None,
                               basis: str | None = None) -> str:
    """Label an observation's evidence strength from its source/basis.

    Benchmark-only rows are always ``benchmark`` regardless of source. A source
    we do not recognise is ``unconfirmed`` (fail weak, never provider-confirmed).
    """
    if basis == CardActivityBasis.BENCHMARK_ONLY.value or reconciliation_state == "benchmark_only":
        return EvidenceStrength.BENCHMARK.value
    return _SOURCE_EVIDENCE_STRENGTH.get(str(source), EvidenceStrength.UNCONFIRMED).value


def assert_evidence_not_overclaimed(source: str | None, evidence_strength: str | None) -> None:
    """Fail closed if a non-provider source claims provider-confirmed evidence.

    SDK/self-reported/on-chain/benchmark observations may never be promoted to
    ``provider_confirmed`` — that label requires genuine provider/issuer
    evidence. Used as a defensive guard on every ingest path.
    """
    if (evidence_strength == EvidenceStrength.PROVIDER_CONFIRMED.value
            and str(source) not in _PROVIDER_CONFIRMED_SOURCES):
        raise EvidenceOverclaimError(
            f"source {source!r} may not be labeled provider_confirmed evidence "
            "without independent provider/issuer evidence"
        )


# ── top-up / spend non-conflation guard ───────────────────────────────────────
# Keys that would represent a single scalar mixing top-up/funding with spend.
# A rollup/surface must NEVER carry one of these — top-up volume and spend volume
# are always separate numbers so top-up can never be presented as card spend.
COMBINED_TOTAL_FORBIDDEN_KEYS = frozenset({
    "total_volume_usd", "combined_volume_usd", "net_volume_usd",
    "gross_volume_usd", "total_amount_usd", "total_usd", "volume_usd",
})


class TopupSpendConflationError(ValueError):
    """Raised when a rollup would sum top-up/funding and spend into one scalar."""


def assert_topup_spend_separated(rollup: dict[str, Any]) -> dict[str, Any]:
    """Hard guard: a card-linked rollup must never expose a combined top-up +
    spend scalar. Returns the rollup unchanged when clean; raises otherwise.

    This is intentionally structural (a forbidden-key check) rather than a
    numeric heuristic: the only safe way to keep top-up and spend un-conflated
    is to never materialize a single number that could mean either.
    """
    present = sorted(k for k in rollup if k in COMBINED_TOTAL_FORBIDDEN_KEYS)
    if present:
        raise TopupSpendConflationError(
            "top-up/funding and spend must never be summed into a single scalar; "
            f"forbidden combined key(s) present: {', '.join(present)}"
        )
    return rollup


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
    # Evidence-strength label (see EvidenceStrength). Populated by ingestion so
    # every stored flow records how strongly it is evidenced. Never persisted as
    # provider_confirmed for a non-provider source.
    evidence_strength: str | None = None

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
