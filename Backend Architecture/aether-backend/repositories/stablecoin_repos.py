"""
Aether Backend — Stablecoin Intelligence Repositories

Typed repositories for the Alembic-owned stablecoin intelligence tables
(migration 20260708_stablecoin_intelligence). One TypedTableRepository
subclass per table; canonical amounts stay Decimal end-to-end.

Observation-only domain: every tenant-scoped row carries
execution_by_aether=False (fail-closed CHECK in the DDL). Fact tables are
append-only; the only mutable current-state surfaces are the finality
checkpoint table and the finality_status projection columns on
observations (see services/stablecoin/finality.py for the rationale).
"""

from __future__ import annotations

from repositories.typed_repo import TypedTableRepository


class StablecoinAssetRepo(TypedTableRepository):
    """Global reference table — canonical stablecoin assets (no tenant_id)."""

    table_name = "stablecoin_assets"
    columns = (
        "canonical_asset_id",
        "symbol",
        "name",
        "issuer_entity_id",
        "issuer_name",
        "backing_model",
        "pegged_to",
        "asset_status",
        "risk_classification",
        "first_seen_at",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("canonical_asset_id",)


class StablecoinDeploymentRepo(TypedTableRepository):
    """Global reference table — per-chain stablecoin deployments."""

    table_name = "stablecoin_deployments"
    columns = (
        "deployment_id",
        "canonical_asset_id",
        "chain_id",
        "network",
        "token_standard",
        "contract_or_mint",
        "decimals",
        "deployment_type",
        "bridge_origin_deployment_id",
        "issuer_verified",
        "active",
        "testnet",
        "first_seen_at",
        "last_seen_at",
        "deprecated_at",
        "data",
    )
    jsonb_columns = frozenset({"data"})
    conflict_key = ("deployment_id",)


class StablecoinObservationRepo(TypedTableRepository):
    """Tenant-scoped append-only on-chain observations.

    finality_status / finalized_at are the single mutable projection on this
    otherwise-immutable fact table (updated via update_by_key by the
    FinalityEngine; the correction trail lives in emitted events).
    """

    table_name = "stablecoin_observations"
    columns = (
        "tenant_id",
        "observation_id",
        "observation_type",
        "deployment_id",
        "canonical_asset_id",
        "chain_id",
        "network",
        "block_number",
        "block_hash",
        "transaction_hash",
        "log_or_instruction_index",
        "amount_atomic",
        "amount_decimal",
        "from_address",
        "to_address",
        "from_wallet_id",
        "to_wallet_id",
        "from_entity_ref",
        "to_entity_ref",
        "counterparty_class",
        "protocol_id",
        "merchant_id",
        "facilitator_id",
        "agent_id",
        "campaign_id",
        "journey_id",
        "session_id",
        "finality_status",
        "finalized_at",
        "classification_confidence",
        "observed_at",
        "ingested_at",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"evidence", "from_entity_ref", "to_entity_ref"})
    conflict_key = ("tenant_id", "idempotency_key")


class SupportAssertionRepo(TypedTableRepository):
    """Tenant-scoped support assertions — corrections append new rows."""

    table_name = "stablecoin_support_assertions"
    columns = (
        "tenant_id",
        "assertion_id",
        "subject_entity_ref",
        "deployment_id",
        "capability",
        "support_status",
        "environment",
        "evidence_type",
        "evidence_reference",
        "first_observed_at",
        "last_observed_at",
        "successful_observation_count",
        "failed_observation_count",
        "confidence",
        "expires_at",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"subject_entity_ref", "evidence"})
    conflict_key = ("tenant_id", "idempotency_key")


class ValuationSnapshotRepo(TypedTableRepository):
    """Tenant-scoped valuation snapshots (append-only)."""

    table_name = "stablecoin_valuation_snapshots"
    columns = (
        "tenant_id",
        "valuation_id",
        "deployment_id",
        "price_usd",
        "peg_deviation_bps",
        "peg_status",
        "source",
        "source_record_id",
        "observed_at",
        "stale_after",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"evidence"})
    conflict_key = ("tenant_id", "idempotency_key")


class FlowAggregateRepo(TypedTableRepository):
    """Tenant-scoped materialized flow aggregates (append-only, versioned)."""

    table_name = "stablecoin_flow_aggregates"
    columns = (
        "tenant_id",
        "flow_aggregate_id",
        "canonical_asset_id",
        "deployment_id",
        "chain_id",
        "window_start",
        "window_end",
        "direction",
        "gross_transfer_volume",
        "finalized_payment_volume",
        "transfer_count",
        "unique_senders",
        "unique_recipients",
        "metric_version",
        "materialized_at",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"evidence"})
    conflict_key = ("tenant_id", "idempotency_key")


class ReconciliationRepo(TypedTableRepository):
    """Tenant-scoped reconciliation records (append-only correction trail)."""

    table_name = "stablecoin_reconciliation_records"
    columns = (
        "tenant_id",
        "reconciliation_id",
        "observation_id",
        "transaction_hash",
        "status",
        "expected_amount",
        "observed_amount",
        "difference",
        "sources_compared",
        "resolved_at",
        "resolution_note",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"sources_compared", "evidence"})
    conflict_key = ("tenant_id", "idempotency_key")


class FinalityCheckpointRepo(TypedTableRepository):
    """Tenant-scoped per-chain finality checkpoints (mutable current state)."""

    table_name = "stablecoin_finality_checkpoints"
    columns = (
        "tenant_id",
        "checkpoint_id",
        "chain_id",
        "confirmed_block_number",
        "confirmed_block_hash",
        "confirmation_horizon",
        "advanced_at",
        "idempotency_key",
        "evidence",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"evidence"})
    conflict_key = ("tenant_id", "chain_id")
