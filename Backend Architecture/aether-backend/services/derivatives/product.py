"""Derivatives PR4 product and operations service.

This module adapts the PR1-PR3 canonical derivatives foundation into tenant and
Kyber-facing product payloads. It intentionally does not execute trades, sign
transactions, mutate venue accounts, or store credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256
from typing import Any, Mapping

from services.derivatives.intelligence import build_profile360_derivatives_summary
from services.derivatives.models import PositionEpochState, PositionSide, PositionStatus

PRODUCT_VERSION = "derivatives-product-v1"
DERIVATIVES_REQUIRED_ENTITLEMENT = "derivatives.enabled"

DERIVATIVES_REALTIME_TOPICS = (
    "tenant.derivatives.position_opened",
    "tenant.derivatives.position_changed",
    "tenant.derivatives.position_closed",
    "tenant.derivatives.liquidation",
    "tenant.derivatives.funding_settled",
    "tenant.derivatives.risk_threshold_crossed",
    "tenant.derivatives.agent_policy_violation",
    "tenant.derivatives.connector_stale",
    "tenant.derivatives.reconciliation_variance",
    "tenant.derivatives.mapping_review_required",
)

DERIVATIVES_ALERT_RULES = (
    "liquidation_proximity",
    "excess_leverage",
    "concentration",
    "margin_utilization",
    "drawdown",
    "agent_policy_violation",
    "ignored_warning",
    "abnormal_fees",
    "abnormal_slippage",
    "connector_stale",
    "position_mismatch",
    "price_source_stale",
    "funding_anomaly",
    "coordinated_behavior_signal",
)

OPERATOR_ACTIONS = frozenset({
    "pause_connector",
    "resume_connector",
    "test_connection",
    "rotate_secret_reference",
    "reprocess_bounded_period",
    "backfill_bounded_period",
    "reconcile_account",
    "reconcile_position",
    "remap_market",
    "rebuild_projection",
    "quarantine_record",
    "resolve_mapping_review",
    "export_audit_evidence",
})

USAGE_METERS = (
    "connected_venues",
    "connected_accounts",
    "ingested_records",
    "active_positions",
    "history_retention_days",
    "realtime_subscriptions",
    "backfill_records",
    "graph_queries",
    "noesis_queries",
    "export_bytes",
    "custom_connector_invocations",
)


@dataclass(frozen=True)
class DerivativesAccountView:
    tenant_id: str
    trading_account_id: str
    venue_id: str
    connection_state: str
    credential_authority: str = "read_only"
    last_sync_at: str | None = None
    historical_coverage_days: int = 0
    reconciliation_status: str = "matched"
    execution_by_aether: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "trading_account_id": self.trading_account_id,
            "venue_id": self.venue_id,
            "connection_state": self.connection_state,
            "credential_authority": self.credential_authority,
            "last_sync_at": self.last_sync_at,
            "historical_coverage_days": self.historical_coverage_days,
            "reconciliation_status": self.reconciliation_status,
            "execution_by_aether": self.execution_by_aether,
        }


@dataclass(frozen=True)
class DerivativesProductSnapshot:
    tenant_id: str
    accounts: tuple[DerivativesAccountView, ...] = field(default_factory=tuple)
    positions: tuple[PositionEpochState, ...] = field(default_factory=tuple)
    alerts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    reconciliation_variances: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class DerivativesProductService:
    """Tenant-safe product facade for derivatives UI, Kyber ops, alerts, and metering."""

    def __init__(self) -> None:
        self._snapshots: dict[str, DerivativesProductSnapshot] = {}
        self._operator_audit: list[dict[str, Any]] = []

    def seed_snapshot(self, snapshot: DerivativesProductSnapshot) -> None:
        self._snapshots[snapshot.tenant_id] = snapshot

    def overview(self, tenant_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(tenant_id)
        positions = self._positions(tenant_id)
        open_positions = [p for p in positions if p.status is PositionStatus.OPEN]
        closed_positions = [p for p in positions if p.status is PositionStatus.CLOSED]
        gross_pnl = sum((p.realized_pnl for p in positions), Decimal("0"))
        fees = sum((p.fees for p in positions), Decimal("0"))
        venues = sorted({a.venue_id for a in snapshot.accounts})
        return {
            "tenant_id": tenant_id,
            "product_version": PRODUCT_VERSION,
            "state": "empty" if not snapshot.accounts and not positions else "complete",
            "connected_accounts": len(snapshot.accounts),
            "connected_venues": len(venues),
            "venue_distribution": venues,
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "net_pnl": str(gross_pnl - fees),
            "fees": str(fees),
            "liquidations": sum(1 for p in positions if p.status.value == "liquidated"),
            "risk_status": "reconciliation_warning" if snapshot.reconciliation_variances else "normal",
            "data_freshness_state": "partial" if not snapshot.accounts else "complete",
            "alerts": list(snapshot.alerts),
            "execution_by_aether": False,
        }

    def accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        return [account.to_dict() for account in self._snapshot(tenant_id).accounts]

    def positions(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        rows = self._positions(tenant_id)
        if status:
            rows = [p for p in rows if p.status.value == status]
        return [self._position_summary(p) for p in rows]

    def position_detail(self, tenant_id: str, epoch_id: str) -> dict[str, Any] | None:
        for position in self._positions(tenant_id):
            if position.epoch_id == epoch_id:
                return {
                    **self._position_summary(position),
                    "lifecycle": {
                        "opened_at": position.opened_at,
                        "closed_at": position.closed_at,
                        "source_fill_ids": list(position.source_fill_ids),
                    },
                    "orders": [],
                    "fills": position.source_fill_ids,
                    "funding": [],
                    "fees": str(position.fees),
                    "collateral": [],
                    "risk_snapshots": [],
                    "agent_decisions": [],
                    "human_decisions": [],
                    "warnings": [],
                    "overrides": [],
                    "campaign_lineage": [],
                    "journey_lineage": [],
                    "evidence": {"source_fill_ids": list(position.source_fill_ids), "evidence_class": "computation"},
                    "reconciliation_status": "matched",
                }
        return None

    def behavior(self, tenant_id: str, window: str = "lifetime") -> dict[str, Any]:
        return build_profile360_derivatives_summary(tenant_id, self._positions(tenant_id), window)

    def realtime_catalog(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "topics": list(DERIVATIVES_REALTIME_TOPICS),
            "durable_source_required": True,
            "resumable": True,
        }

    def alert_catalog(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "rules": [{"rule_key": rule, "evidence_required": True, "enabled": True} for rule in DERIVATIVES_ALERT_RULES],
        }

    def meter_usage(self, tenant_id: str, meter: str, quantity: Decimal) -> dict[str, Any]:
        # Delegates to the shared DerivativesMeter hook so the in-memory rollup
        # AND any installed durable sink observe one consistent view.
        from services.derivatives.meter import derivatives_meter

        return derivatives_meter.record(tenant_id, meter, quantity)

    def kyber_fleet(self, operator_tenant_id: str) -> dict[str, Any]:
        from services.derivatives import counters

        computed = counters.compute_kyber_fleet_sync(operator_tenant_id=operator_tenant_id)
        snapshot_tenants = sorted(self._snapshots)
        snapshot_accounts = sum(len(s.accounts) for s in self._snapshots.values())
        snapshot_venues = len({a.venue_id for s in self._snapshots.values() for a in s.accounts})
        return {
            "operator_tenant_id": operator_tenant_id,
            "tenant_count": max(computed["tenant_count"], len(snapshot_tenants)),
            "account_count": max(computed["account_count"], snapshot_accounts),
            "venue_count": max(computed["venue_count"], snapshot_venues),
            "authentication_failures": computed["authentication_failures"],
            "rate_limit_events": computed["rate_limit_events"],
            "snapshot_age_seconds_max": computed["snapshot_age_seconds_max"],
            "stream_lag_seconds_max": computed["stream_lag_seconds_max"],
            "checkpoint_lag_seconds_max": computed["checkpoint_lag_seconds_max"],
            "backfill_state": computed["backfill_state"],
            "execution_by_aether": False,
        }

    def kyber_data_quality(self, operator_tenant_id: str) -> dict[str, Any]:
        from services.derivatives import counters

        computed = counters.compute_kyber_data_quality_sync(
            operator_tenant_id=operator_tenant_id,
        )
        variance_count = sum(
            len(s.reconciliation_variances) for s in self._snapshots.values()
        )
        return {
            "operator_tenant_id": operator_tenant_id,
            "duplicates": computed["duplicates"],
            "reordered_records": computed["reordered_records"],
            "missing_intervals": computed["missing_intervals"],
            "schema_drift": computed["schema_drift"],
            "mapping_failures": computed["mapping_failures"],
            "price_gaps": computed["price_gaps"],
            "funding_gaps": computed["funding_gaps"],
            "snapshot_delta_mismatches": (
                computed["snapshot_delta_mismatches"] + variance_count
            ),
            "stale_positions": computed["stale_positions"],
            "orphan_records": computed["orphan_records"],
        }

    def kyber_reconciliation(self, operator_tenant_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        snapshots = [self._snapshot(tenant_id)] if tenant_id else list(self._snapshots.values())
        variances = [v for snapshot in snapshots for v in snapshot.reconciliation_variances]
        return {"operator_tenant_id": operator_tenant_id, "tenant_id": tenant_id, "variance_count": len(variances), "variances": variances}

    def kyber_graph_quality(self, operator_tenant_id: str) -> dict[str, Any]:
        from services.derivatives import counters

        computed = counters.compute_kyber_graph_quality_sync(
            operator_tenant_id=operator_tenant_id,
        )
        return {
            "operator_tenant_id": operator_tenant_id,
            "projection_lag_seconds": computed["projection_lag_seconds"],
            "failed_mutations": computed["failed_mutations"],
            "unknown_edge_attempts": computed["unknown_edge_attempts"],
            "missing_evidence": computed["missing_evidence"],
            "low_confidence_links": computed["low_confidence_links"],
            "orphan_positions": computed["orphan_positions"],
            "tenant_isolation_rejections": computed["tenant_isolation_rejections"],
        }

    def kyber_intelligence_quality(self, operator_tenant_id: str) -> dict[str, Any]:
        return {
            "operator_tenant_id": operator_tenant_id,
            "feature_freshness_state": "fresh",
            "deterministic_rule_coverage": "complete",
            "model_readiness_state": "not_required_pr4",
            "false_positive_review_queue": 0,
            "explanation_coverage": "complete",
        }

    def record_operator_action(self, operator_tenant_id: str, tenant_id: str, action: str, scope: Mapping[str, Any]) -> dict[str, Any]:
        if action not in OPERATOR_ACTIONS:
            raise ValueError(f"unsupported derivatives operator action: {action}")
        if not tenant_id:
            raise ValueError("operator action must be tenant-scoped")
        action_id = "derivatives-op:" + sha256(f"{operator_tenant_id}|{tenant_id}|{action}|{sorted(scope.items())}".encode()).hexdigest()
        row = {
            "action_id": action_id,
            "operator_tenant_id": operator_tenant_id,
            "tenant_id": tenant_id,
            "action": action,
            "scope": dict(scope),
            "status": "accepted",
            "audited": True,
            "idempotent": True,
            "execution_by_aether": False,
        }
        self._operator_audit.append(row)
        return row

    def _snapshot(self, tenant_id: str | None) -> DerivativesProductSnapshot:
        if tenant_id is None:
            return DerivativesProductSnapshot(tenant_id="")
        return self._snapshots.get(tenant_id, DerivativesProductSnapshot(tenant_id=tenant_id))

    def _positions(self, tenant_id: str) -> list[PositionEpochState]:
        return [p for p in self._snapshot(tenant_id).positions if p.tenant_id == tenant_id]

    def _position_summary(self, position: PositionEpochState) -> dict[str, Any]:
        return {
            "tenant_id": position.tenant_id,
            "position_epoch_id": position.epoch_id,
            "trading_account_id": position.trading_account_id,
            "canonical_market_id": position.canonical_market_id,
            "side": position.side.value,
            "status": position.status.value,
            "size": str(position.size),
            "entry_price": str(position.entry_price) if position.entry_price is not None else None,
            "realized_pnl": str(position.realized_pnl),
            "fees": str(position.fees),
            "net_realized_pnl": str(position.net_realized_pnl),
            "opened_at": position.opened_at,
            "closed_at": position.closed_at,
            "execution_by_aether": False,
        }


product_service = DerivativesProductService()


def seed_demo_derivatives_snapshot(tenant_id: str) -> None:
    """Seed deterministic local-mode data for tests and empty-product previews."""
    product_service.seed_snapshot(DerivativesProductSnapshot(
        tenant_id=tenant_id,
        accounts=(DerivativesAccountView(
            tenant_id=tenant_id,
            trading_account_id="acct-demo-1",
            venue_id="hyperliquid",
            connection_state="active",
            last_sync_at="2026-07-04T00:00:00Z",
            historical_coverage_days=30,
        ),),
        positions=(PositionEpochState(
            tenant_id=tenant_id,
            trading_account_id="acct-demo-1",
            canonical_market_id="mkt-btc-usd-perp",
            epoch_id="epoch-demo-1",
            side=PositionSide.LONG,
            status=PositionStatus.CLOSED,
            size=Decimal("0"),
            realized_pnl=Decimal("42.00"),
            fees=Decimal("2.00"),
            opened_at="2026-07-01T00:00:00Z",
            closed_at="2026-07-02T00:00:00Z",
            source_fill_ids=["fill-demo-open", "fill-demo-close"],
        ),),
    ))
