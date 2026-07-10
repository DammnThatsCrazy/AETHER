"""Durable repositories for Stablecoin Intelligence PR1 foundation."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now


class StablecoinDeploymentRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_deployments")


class StablecoinObservationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_observations")

    @staticmethod
    def observation_key(record: dict[str, Any]) -> str:
        required = ["tenant_id", "chain_id", "network", "deployment_id", "transaction_hash"]
        missing = [k for k in required if not record.get(k)]
        if missing:
            raise ValueError(f"missing stablecoin observation identity: {','.join(missing)}")
        idx = record.get("log_or_instruction_index", "")
        raw_key = ":".join(str(record[k]) for k in required) + f":{idx}"
        return hashlib.sha256(raw_key.encode()).hexdigest()[:32]

    async def upsert_observation(self, record: dict[str, Any]) -> dict[str, Any]:
        if not record.get("tenant_id"):
            raise ValueError("tenant_id is required")
        record_id = record.get("observation_id") or self.observation_key(record)
        data = {**record, "observation_id": record_id, "updated_at": utc_now().isoformat()}
        existing = await self.find_by_id(record_id)
        if existing:
            return await self.update(record_id, {**existing, **data})
        data.setdefault("created_at", data["updated_at"])
        return await self.insert(record_id, data)


class StablecoinSupportAssertionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_support_assertions")


class StablecoinReconciliationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_reconciliation_results")


class StablecoinGoldIdentity:
    @staticmethod
    def key(
        *,
        tenant_id: str,
        metric_name: str,
        metric_version: str,
        entity_id: str,
        entity_type: str,
        canonical_asset_id: str,
        deployment_id: str,
        chain_id: str,
        window_start: str,
        window_end: str,
        dimensions: Optional[dict[str, Any]] = None,
        source: str = "",
    ) -> str:
        if not tenant_id:
            raise ValueError("tenant_id is required for tenant-owned Gold stablecoin metrics")
        payload = {
            "tenant_id": tenant_id,
            "metric_name": metric_name,
            "metric_version": metric_version,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_asset_id": canonical_asset_id,
            "deployment_id": deployment_id,
            "chain_id": chain_id,
            "window_start": window_start,
            "window_end": window_end,
            "dimensions": dimensions or {},
            "source": source,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:40]


class StablecoinGoldRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("gold_stablecoin_metrics")

    async def materialize_metric(self, **kwargs: Any) -> dict[str, Any]:
        metric_id = StablecoinGoldIdentity.key(
            **{k: kwargs.get(k, "") for k in [
                "tenant_id", "metric_name", "metric_version", "entity_id", "entity_type",
                "canonical_asset_id", "deployment_id", "chain_id", "window_start", "window_end",
            ]},
            dimensions=kwargs.get("dimensions"),
            source=kwargs.get("source", ""),
        )
        data = {**kwargs, "gold_id": metric_id, "materialized_at": utc_now().isoformat()}
        existing = await self.find_by_id(metric_id)
        if existing:
            return await self.update(metric_id, {**existing, **data})
        return await self.insert(metric_id, data)


class StablecoinRemediationAuditRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_remediation_audit")


class StablecoinMarketBenchmarkRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_market_benchmarks")


class StablecoinIdentityLinkRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_identity_links")


class StablecoinGraphProjectionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_graph_projection_outbox")


class StablecoinProviderHealthRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_provider_health")


class StablecoinIngestionCheckpointRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_ingestion_checkpoints")


class StablecoinPollingCheckpointRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_polling_checkpoints")


# ═══════════════════════════════════════════════════════════════════════════
# Typed repositories — Alembic-owned stablecoin intelligence tables
# (migration 20260708_stablecoin_intelligence). One TypedTableRepository
# subclass per table; canonical amounts stay Decimal end-to-end. Every
# tenant-scoped row carries execution_by_aether=False (fail-closed CHECK).
# These coexist with the JSONB repositories above: the *Repository classes
# back services/stablecoins (observer stack), the *Repo classes back
# services/stablecoin (economic intelligence domain).
# ═══════════════════════════════════════════════════════════════════════════


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
