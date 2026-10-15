"""
Aether Backend — Derivatives Intelligence typed repositories.

TypedTableRepository subclasses for every table owned by the two derivatives
Alembic migrations:

  - alembic/versions/20260708_derivatives_foundation_adoption.py
  - alembic/versions/20260708_derivatives_runtime.py

House rules (enforced by the DDL, mirrored here):
  - OBSERVATION-ONLY domain: every tenant-scoped row carries
    execution_by_aether = FALSE with a fail-closed CHECK constraint. No code
    path in this module places, amends, or cancels anything.
  - Canonical amounts live in NUMERIC(38, 18) columns and transit as
    decimal.Decimal — never floats (see typed_repo.as_decimal).
  - Fact tables append correction rows; only registries/checkpoints are
    mutable via update_by_key.
  - Global reference tables (venues, deployments, instruments, markets) use
    their natural primary key as the idempotency conflict target; tenant
    tables use (tenant_id, idempotency_key).
"""

from __future__ import annotations

from repositories.typed_repo import TypedTableRepository, as_decimal  # noqa: F401

# Shared trailing columns for the runtime-layer tenant tables
# (20260708_derivatives_runtime house rules).
_RUNTIME_TAIL: tuple[str, ...] = (
    "idempotency_key",
    "evidence",
    "execution_by_aether",
    "created_at",
    "updated_at",
)


# ═══════════════════════════════════════════════════════════════════════════
# Foundation tables — global reference registries
# ═══════════════════════════════════════════════════════════════════════════

class VenueRepo(TypedTableRepository):
    """derivatives_trading_venues — global venue registry."""

    table_name = "derivatives_trading_venues"
    columns = (
        "venue_id",
        "venue_type",
        "display_name",
        "website_url",
        "global_reference",
        "created_at",
    )
    conflict_key = ("venue_id",)


class VenueDeploymentRepo(TypedTableRepository):
    """derivatives_venue_deployments — global venue deployment registry."""

    table_name = "derivatives_venue_deployments"
    columns = (
        "venue_deployment_id",
        "venue_id",
        "deployment",
        "chain_id",
        "region",
        "global_reference",
        "created_at",
    )
    conflict_key = ("venue_deployment_id",)


class InstrumentRepo(TypedTableRepository):
    """derivatives_instruments — global canonical instrument registry."""

    table_name = "derivatives_instruments"
    columns = (
        "canonical_instrument_id",
        "instrument_type",
        "underlying_asset_id",
        "quote_asset_id",
        "settlement_asset_id",
        "contract_type",
        "contract_multiplier",
        "inverse_or_linear",
        "expiry_at",
        "global_reference",
        "created_at",
    )
    conflict_key = ("canonical_instrument_id",)


class MarketRepo(TypedTableRepository):
    """derivatives_markets — global venue-market registry."""

    table_name = "derivatives_markets"
    columns = (
        "canonical_market_id",
        "canonical_instrument_id",
        "venue_id",
        "venue_deployment_id",
        "venue_market_id",
        "underlying_asset_id",
        "quote_asset_id",
        "settlement_asset_id",
        "instrument_type",
        "contract_type",
        "contract_multiplier",
        "inverse_or_linear",
        "expiry_at",
        "price_precision",
        "size_precision",
        "margin_modes",  # TEXT[] — asyncpg list, not JSONB
        "status",
        "first_seen_at",
        "last_seen_at",
        "global_reference",
    )
    conflict_key = ("canonical_market_id",)


# ═══════════════════════════════════════════════════════════════════════════
# Foundation tables — tenant-scoped facts and registries
# ═══════════════════════════════════════════════════════════════════════════

class TradingAccountRepo(TypedTableRepository):
    """derivatives_trading_accounts — read-only observed account links."""

    table_name = "derivatives_trading_accounts"
    columns = (
        "tenant_id",
        "trading_account_id",
        "venue_id",
        "venue_deployment_id",
        "external_account_ref",
        "owner_entity_kind",
        "owner_entity_id",
        "credential_reference_id",
        "connector_state",
        "data_quality_state",
        "idempotency_key",
        "execution_by_aether",
        "created_at",
    )


class OrderRepo(TypedTableRepository):
    """derivatives_orders — observed order facts (append-only)."""

    table_name = "derivatives_orders"
    columns = (
        "tenant_id",
        "order_id",
        "trading_account_id",
        "canonical_market_id",
        "order_type",
        "order_side",
        "order_status",
        "time_in_force",
        "quantity",
        "limit_price",
        "origin",
        "source_refs",
        "idempotency_key",
        "execution_by_aether",
        "recorded_at",
    )
    jsonb_columns = frozenset({"source_refs"})


class FillRepo(TypedTableRepository):
    """derivatives_fills — observed trade fills (append-only)."""

    table_name = "derivatives_fills"
    columns = (
        "tenant_id",
        "fill_id",
        "order_id",
        "trading_account_id",
        "canonical_market_id",
        "side",
        "liquidity_role",
        "price",
        "quantity",
        "fee_amount",
        "fee_asset_id",
        "executed_at",
        "source_refs",
        "idempotency_key",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"source_refs"})


class PositionRepo(TypedTableRepository):
    """derivatives_positions — observed position facts."""

    table_name = "derivatives_positions"
    columns = (
        "tenant_id",
        "position_id",
        "position_epoch_id",
        "trading_account_id",
        "canonical_market_id",
        "side",
        "status",
        "size",
        "entry_price",
        "realized_pnl",
        "unrealized_pnl",
        "accounting_method",
        "idempotency_key",
        "execution_by_aether",
        "updated_at",
    )


class PositionEpochRepo(TypedTableRepository):
    """derivatives_position_epochs — flat-to-flat position lifecycles."""

    table_name = "derivatives_position_epochs"
    columns = (
        "tenant_id",
        "position_epoch_id",
        "position_id",
        "opened_at",
        "closed_at",
        "open_size",
        "close_size",
        "idempotency_key",
        "execution_by_aether",
    )


class ConnectorCheckpointRepo(TypedTableRepository):
    """derivatives_connector_checkpoints — adapter pull cursors (mutable state)."""

    table_name = "derivatives_connector_checkpoints"
    columns = (
        "tenant_id",
        "connector_checkpoint_id",
        "connector_id",
        "state",
        "checkpoint_value",
        "advanced_at",
        "idempotency_key",
        "execution_by_aether",
    )


class ReconciliationVarianceRepo(TypedTableRepository):
    """derivatives_reconciliation_variances — snapshot-vs-projection diffs."""

    table_name = "derivatives_reconciliation_variances"
    columns = (
        "tenant_id",
        "reconciliation_variance_id",
        "variance_type",
        "expected_value",
        "observed_value",
        "difference",
        "severity",
        "status",
        "source_refs",
        "first_seen_at",
        "last_seen_at",
        "idempotency_key",
        "execution_by_aether",
    )
    jsonb_columns = frozenset({"source_refs"})


# ═══════════════════════════════════════════════════════════════════════════
# Runtime tables — strategies, economics, market state, silver facts
# ═══════════════════════════════════════════════════════════════════════════

class StrategyRepo(TypedTableRepository):
    """derivatives_strategies — tenant strategy registry."""

    table_name = "derivatives_strategies"
    columns = ("tenant_id", "strategy_id", "owner_ref", "name", "data") + _RUNTIME_TAIL
    jsonb_columns = frozenset({"owner_ref", "data", "evidence"})


class StrategyVersionRepo(TypedTableRepository):
    """derivatives_strategy_versions — immutable strategy versions."""

    table_name = "derivatives_strategy_versions"
    columns = (
        "tenant_id",
        "strategy_version_id",
        "strategy_id",
        "version",
        "config",
        "effective_from",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"config", "evidence"})


class ExecutionDecisionRepo(TypedTableRepository):
    """derivatives_execution_decisions — observed decision journal
    (decisions made elsewhere; Aether records, never executes)."""

    table_name = "derivatives_execution_decisions"
    columns = (
        "tenant_id",
        "execution_decision_id",
        "origin",
        "strategy_version_id",
        "order_id",
        "decision_at",
        "data",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"data", "evidence"})


class FundingPaymentRepo(TypedTableRepository):
    """derivatives_funding_payments — observed funding economics."""

    table_name = "derivatives_funding_payments"
    columns = (
        "tenant_id",
        "funding_payment_id",
        "position_id",
        "trading_account_id",
        "canonical_market_id",
        "amount",
        "asset_id",
        "settled_at",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"evidence"})


class FeeRepo(TypedTableRepository):
    """derivatives_fees — observed trading fees."""

    table_name = "derivatives_fees"
    columns = (
        "tenant_id",
        "trading_fee_id",
        "fee_type",
        "amount",
        "asset_id",
        "related_ref",
        "charged_at",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"related_ref", "evidence"})


class LiquidationRepo(TypedTableRepository):
    """derivatives_liquidations — observed liquidation events."""

    table_name = "derivatives_liquidations"
    columns = (
        "tenant_id",
        "liquidation_event_id",
        "position_id",
        "liquidation_type",
        "size",
        "price",
        "occurred_at",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"evidence"})


class PriceObservationRepo(TypedTableRepository):
    """derivatives_price_observations — mark/index/oracle price facts."""

    table_name = "derivatives_price_observations"
    columns = (
        "tenant_id",
        "price_observation_id",
        "canonical_market_id",
        "price_type",
        "price",
        "source_finality",
        "observed_at",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"evidence"})


class RiskPolicyRepo(TypedTableRepository):
    """derivatives_risk_policies — read-only-authority risk policy registry."""

    table_name = "derivatives_risk_policies"
    columns = (
        "tenant_id",
        "risk_policy_id",
        "subject_ref",
        "severity",
        "max_leverage",
        "max_notional",
        "loss_limit",
        "authority_type",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"subject_ref", "evidence"})


class PnlSnapshotRepo(TypedTableRepository):
    """derivatives_pnl_snapshots — materialized P&L / exposure snapshots."""

    table_name = "derivatives_pnl_snapshots"
    columns = (
        "tenant_id",
        "pnl_snapshot_id",
        "trading_account_id",
        "canonical_market_id",
        "realized_pnl",
        "unrealized_pnl",
        "gross_exposure",
        "net_exposure",
        "accounting_method",
        "as_of",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"evidence"})


class StreamGapRepo(TypedTableRepository):
    """derivatives_stream_gaps — detected/recovered sequence gaps."""

    table_name = "derivatives_stream_gaps"
    columns = (
        "tenant_id",
        "stream_gap_id",
        "venue_id",
        "canonical_market_id",
        "channel",
        "expected_sequence",
        "received_sequence",
        "detected_at",
        "recovered_at",
        "status",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"evidence"})


class SilverDerivativesFactRepo(TypedTableRepository):
    """silver_derivatives_facts — canonical event projection (catch-all facts)."""

    table_name = "silver_derivatives_facts"
    columns = (
        "fact_id",
        "tenant_id",
        "source_event_id",
        "entity_id",
        "event_type",
        "occurred_at",
        "payload",
        "trading_account_id",
        "canonical_market_id",
        "amount",
        "asset_id",
    ) + _RUNTIME_TAIL
    jsonb_columns = frozenset({"payload", "evidence"})


ALL_DERIVATIVES_REPOS: tuple[type[TypedTableRepository], ...] = (
    VenueRepo,
    VenueDeploymentRepo,
    InstrumentRepo,
    MarketRepo,
    TradingAccountRepo,
    OrderRepo,
    FillRepo,
    PositionRepo,
    PositionEpochRepo,
    StrategyRepo,
    StrategyVersionRepo,
    ExecutionDecisionRepo,
    FundingPaymentRepo,
    FeeRepo,
    LiquidationRepo,
    PriceObservationRepo,
    RiskPolicyRepo,
    PnlSnapshotRepo,
    StreamGapRepo,
    ConnectorCheckpointRepo,
    ReconciliationVarianceRepo,
    SilverDerivativesFactRepo,
)
