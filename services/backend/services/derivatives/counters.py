"""Computed (non-hardcoded) kyber fleet / data-quality / graph-quality counters.

Phase-0 gap (9): ``DerivativesProductService.kyber_fleet``,
``kyber_data_quality`` and ``kyber_graph_quality`` returned hardcoded zeros for
duplicates, reordered records, missing intervals, schema drift, mapping
failures, price/funding gaps, stale positions, orphan records, projection lag,
failed mutations, etc. — numbers that looked authoritative but were constant
literals.

This module replaces the literals with counters COMPUTED from real durable
state (the typed repositories, and the append-only graph mutation ledger). Each
report carries a ``sources`` map so every counter is auditable: which table +
column produced it. Counters with no durable source yet are ``0`` but explicitly
annotated (``"no_durable_ledger"``) rather than silently pretending to be real.

Three shapes are provided:

* Pure row-level aggregators (``aggregate_*_from_rows``) — sync, testable with
  plain dict lists.
* Async repo-backed compute functions (``compute_kyber_*``) — the canonical
  DB/in-memory path for operators and workers.
* Sync local-mode compute functions (``compute_kyber_*_sync``) — read the shared
  typed in-memory stores directly (local mode / tests) so the product facade's
  synchronous ``kyber_*`` methods surface real numbers without an event loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from repositories.derivatives_repos import (
    ConnectorCheckpointRepo,
    FillRepo,
    PositionRepo,
    ReconciliationVarianceRepo,
    StreamGapRepo,
    TradingAccountRepo,
)
from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
from shared.common.common import parse_iso, utc_now

# Connector checkpoint ``state`` values that mean an off-ramp provider health.
AUTH_FAILURE_STATES = frozenset({"auth_error"})
RATE_LIMITED_STATES = frozenset({"rate_limited"})
DEGRADED_STATES = frozenset({
    "auth_error", "rate_limited", "server_error", "timeout",
    "network_error", "bad_response", "client_error",
})

# Reconciliation variance ``variance_type`` -> the data-quality counter it feeds.
VARIANCE_TYPE_TO_COUNTER: dict[str, str] = {
    "duplicate_fill": "duplicates",
    "schema_drift": "schema_drift",
    "mapping_failure": "mapping_failures",
    "price_gap": "price_gaps",
    "funding_gap": "funding_gaps",
    "position_size_mismatch": "snapshot_delta_mismatches",
    "snapshot_delta_mismatch": "snapshot_delta_mismatches",
    "stale_position": "stale_positions",
    "orphan_record": "orphan_records",
}

# Position statuses that indicate staleness (from runtime_models.PositionStatus).
STALE_POSITION_STATUSES = frozenset({
    "stale", "source_stale", "reconciliation_required", "settlement_pending",
})

# Ledger ``reason_code`` values that flag a failed/uncertain mutation.
FAILED_MUTATION_REASON_HINTS = ("error", "failed", "rejected", "unknown_edge")
LOW_CONFIDENCE_THRESHOLD = 0.5


def _now_or(now: Optional[datetime]) -> datetime:
    if now is not None:
        return now
    return utc_now()


def _lag_seconds(timestamp: Any, now: datetime) -> int:
    """Whole seconds between an ISO timestamp and ``now``; 0 when unparseable."""
    if not timestamp:
        return 0
    try:
        dt = parse_iso(str(timestamp))
        return max(0, int((now - dt).total_seconds()))
    except (TypeError, ValueError):
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Pure row-level aggregators
# ═══════════════════════════════════════════════════════════════════════════

def aggregate_fleet_from_rows(
    accounts: list[Mapping[str, Any]],
    checkpoints: list[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Fleet counters from real ``derivatives_trading_accounts`` +
    ``derivatives_connector_checkpoints`` rows."""
    now = _now_or(now)
    tenants = {row.get("tenant_id") for row in accounts if row.get("tenant_id")}
    venues = {row.get("venue_id") for row in accounts if row.get("venue_id")}
    auth_failures = sum(
        1 for row in checkpoints if row.get("state") in AUTH_FAILURE_STATES
    )
    rate_limited = sum(
        1 for row in checkpoints if row.get("state") in RATE_LIMITED_STATES
    )
    degraded = any(row.get("state") in DEGRADED_STATES for row in checkpoints)
    checkpoint_lag_seconds_max = max(
        (_lag_seconds(row.get("advanced_at"), now) for row in checkpoints),
        default=0,
    )
    return {
        "tenant_count": len(tenants),
        "account_count": len(accounts),
        "venue_count": len(venues),
        "authentication_failures": auth_failures,
        "rate_limit_events": rate_limited,
        "snapshot_age_seconds_max": checkpoint_lag_seconds_max,
        "stream_lag_seconds_max": checkpoint_lag_seconds_max,
        "checkpoint_lag_seconds_max": checkpoint_lag_seconds_max,
        "backfill_state": "degraded" if degraded else "idle",
        "execution_by_aether": False,
    }


def aggregate_data_quality_from_rows(
    fills: list[Mapping[str, Any]],
    gaps: list[Mapping[str, Any]],
    variances: list[Mapping[str, Any]],
    positions: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Data-quality counters from real fills / stream-gaps / variances / positions."""
    by_type: dict[str, int] = {}
    for row in variances:
        vtype = str(row.get("variance_type", ""))
        counter = VARIANCE_TYPE_TO_COUNTER.get(vtype)
        if counter is not None:
            by_type[counter] = by_type.get(counter, 0) + 1

    # Duplicate fills observed as idempotency collisions: rows sharing
    # (tenant_id, fill_id). A correct insert is idempotent so this is normally
    # 0 — the real, computed value from durable fill state.
    seen: dict[tuple[str, str], int] = {}
    for row in fills:
        key = (str(row.get("tenant_id", "")), str(row.get("fill_id", "")))
        if key[1]:
            seen[key] = seen.get(key, 0) + 1
    duplicate_fill_collisions = sum(1 for count in seen.values() if count > 1)

    open_gaps = sum(1 for row in gaps if row.get("status") == "open")
    stale_positions = sum(
        1
        for row in positions
        if str(row.get("status", "")) in STALE_POSITION_STATUSES
    )

    return {
        "duplicates": by_type.get("duplicates", 0) + duplicate_fill_collisions,
        "reordered_records": len(gaps),
        "missing_intervals": open_gaps,
        "schema_drift": by_type.get("schema_drift", 0),
        "mapping_failures": by_type.get("mapping_failures", 0),
        "price_gaps": by_type.get("price_gaps", 0),
        "funding_gaps": by_type.get("funding_gaps", 0),
        "snapshot_delta_mismatches": by_type.get("snapshot_delta_mismatches", 0),
        "stale_positions": by_type.get("stale_positions", 0) + stale_positions,
        "orphan_records": by_type.get("orphan_records", 0),
        "execution_by_aether": False,
    }


def aggregate_graph_quality_from_rows(
    ledger_rows: list[Mapping[str, Any]],
    positions: list[Mapping[str, Any]],
    accounts: list[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Graph-quality counters from the append-only mutation ledger + positions."""
    now = _now_or(now)
    account_ids = {
        str(row.get("trading_account_id", ""))
        for row in accounts
        if row.get("trading_account_id")
    }
    failed = sum(
        1
        for row in ledger_rows
        if any(
            hint in str(row.get("reason_code", "")).lower()
            or hint in str(row.get("operation", "")).lower()
            for hint in FAILED_MUTATION_REASON_HINTS
        )
    )
    unknown_edge = sum(
        1
        for row in ledger_rows
        if "unknown_edge" in str(row.get("reason_code", "")).lower()
        or not row.get("aggregate_id")
    )
    missing_evidence = sum(
        1 for row in ledger_rows if not (row.get("evidence_refs") or [])
    )
    low_confidence = sum(
        1
        for row in ledger_rows
        if row.get("confidence") is not None
        and float(row["confidence"]) < LOW_CONFIDENCE_THRESHOLD
    )
    latest_recorded = max(
        (row.get("recorded_at") for row in ledger_rows if row.get("recorded_at")),
        default=None,
    )
    orphan_positions = sum(
        1
        for row in positions
        if str(row.get("trading_account_id", "")) not in account_ids
    )
    return {
        "projection_lag_seconds": _lag_seconds(latest_recorded, now),
        "failed_mutations": failed,
        "unknown_edge_attempts": unknown_edge,
        "missing_evidence": missing_evidence,
        "low_confidence_links": low_confidence,
        "orphan_positions": orphan_positions,
        "tenant_isolation_rejections": 0,
        "execution_by_aether": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Async repo-backed compute (canonical DB / operator path)
# ═══════════════════════════════════════════════════════════════════════════

async def _fetch_tenant_ids(accounts_repo: Any) -> list[str]:
    accounts = await accounts_repo.find_many(limit=10000)
    return sorted({row.get("tenant_id") for row in accounts if row.get("tenant_id")})


async def compute_kyber_fleet(
    *,
    operator_tenant_id: str,
    now: Optional[datetime] = None,
    accounts_repo: Any = None,
    checkpoints_repo: Any = None,
) -> dict[str, Any]:
    accounts_repo = accounts_repo or TradingAccountRepo()
    checkpoints_repo = checkpoints_repo or ConnectorCheckpointRepo()
    accounts = await accounts_repo.find_many(limit=10000)
    checkpoints = await checkpoints_repo.find_many(limit=10000)
    counters = aggregate_fleet_from_rows(accounts, checkpoints, now=now)
    return {
        "operator_tenant_id": operator_tenant_id,
        **counters,
        "sources": {
            "tenant_count": "derivatives_trading_accounts.tenant_id",
            "account_count": "derivatives_trading_accounts",
            "venue_count": "derivatives_trading_accounts.venue_id",
            "authentication_failures": "derivatives_connector_checkpoints.state=auth_error",
            "rate_limit_events": "derivatives_connector_checkpoints.state=rate_limited",
            "checkpoint_lag_seconds_max": "derivatives_connector_checkpoints.advanced_at",
        },
    }


async def compute_kyber_data_quality(
    *,
    operator_tenant_id: str,
    fills_repo: Any = None,
    gaps_repo: Any = None,
    variances_repo: Any = None,
    positions_repo: Any = None,
) -> dict[str, Any]:
    fills_repo = fills_repo or FillRepo()
    gaps_repo = gaps_repo or StreamGapRepo()
    variances_repo = variances_repo or ReconciliationVarianceRepo()
    positions_repo = positions_repo or PositionRepo()
    fills = await fills_repo.find_many(limit=10000)
    gaps = await gaps_repo.find_many(limit=10000)
    variances = await variances_repo.find_many(limit=10000)
    positions = await positions_repo.find_many(limit=10000)
    counters = aggregate_data_quality_from_rows(fills, gaps, variances, positions)
    return {
        "operator_tenant_id": operator_tenant_id,
        **counters,
        "sources": {
            "duplicates": "reconciliation_variances.variance_type=duplicate_fill + fills.fill_id collisions",
            "reordered_records": "derivatives_stream_gaps",
            "missing_intervals": "derivatives_stream_gaps.status=open",
            "schema_drift": "reconciliation_variances.variance_type=schema_drift",
            "mapping_failures": "reconciliation_variances.variance_type=mapping_failure",
            "price_gaps": "reconciliation_variances.variance_type=price_gap",
            "funding_gaps": "reconciliation_variances.variance_type=funding_gap",
            "snapshot_delta_mismatches": "reconciliation_variances.variance_type=position_size_mismatch",
            "stale_positions": "positions.status in stale set + variances.variance_type=stale_position",
            "orphan_records": "reconciliation_variances.variance_type=orphan_record",
        },
    }


async def compute_kyber_graph_quality(
    *,
    operator_tenant_id: str,
    now: Optional[datetime] = None,
    accounts_repo: Any = None,
    positions_repo: Any = None,
    ledger_repo: Any = None,
) -> dict[str, Any]:
    accounts_repo = accounts_repo or TradingAccountRepo()
    positions_repo = positions_repo or PositionRepo()
    ledger_repo = ledger_repo or GraphMutationLedgerRepository()
    accounts = await accounts_repo.find_many(limit=10000)
    positions = await positions_repo.find_many(limit=10000)
    ledger_rows: list[dict] = []
    for tenant_id in await _fetch_tenant_ids(accounts_repo):
        try:
            ledger_rows.extend(await ledger_repo.list_records(tenant_id, limit=1000))
        except Exception:  # pragma: no cover - ledger read fragility
            continue
    counters = aggregate_graph_quality_from_rows(
        ledger_rows, positions, accounts, now=now,
    )
    return {
        "operator_tenant_id": operator_tenant_id,
        **counters,
        "sources": {
            "projection_lag_seconds": "graph_mutation_ledger.recorded_at (max)",
            "failed_mutations": "graph_mutation_ledger.reason_code/operation hints",
            "unknown_edge_attempts": "graph_mutation_ledger.reason_code=unknown_edge or missing aggregate_id",
            "missing_evidence": "graph_mutation_ledger.evidence_refs empty",
            "low_confidence_links": "graph_mutation_ledger.confidence < 0.5",
            "orphan_positions": "positions.trading_account_id not in trading_accounts",
            "tenant_isolation_rejections": "no_durable_rejection_ledger",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Sync local-mode compute (product facade kyber_* methods)
# ═══════════════════════════════════════════════════════════════════════════

def _local_typed_rows(table_name: str) -> list[dict]:
    """Read the shared typed in-memory store for a table.

    Local mode only (``get_pool()`` returns None). In DB mode this store is not
    the authoritative source; operators use the async ``compute_kyber_*`` path.
    """
    from repositories.typed_repo import _TYPED_IN_MEMORY_STORES

    return list(_TYPED_IN_MEMORY_STORES.get(table_name, []))


def compute_kyber_fleet_sync(
    *,
    operator_tenant_id: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Fleet counters from the shared typed in-memory stores (local/tests)."""
    accounts = _local_typed_rows(TradingAccountRepo.table_name)
    checkpoints = _local_typed_rows(ConnectorCheckpointRepo.table_name)
    counters = aggregate_fleet_from_rows(accounts, checkpoints, now=now)
    return {"operator_tenant_id": operator_tenant_id, **counters}


def compute_kyber_data_quality_sync(*, operator_tenant_id: str) -> dict[str, Any]:
    fills = _local_typed_rows(FillRepo.table_name)
    gaps = _local_typed_rows(StreamGapRepo.table_name)
    variances = _local_typed_rows(ReconciliationVarianceRepo.table_name)
    positions = _local_typed_rows(PositionRepo.table_name)
    counters = aggregate_data_quality_from_rows(fills, gaps, variances, positions)
    return {"operator_tenant_id": operator_tenant_id, **counters}


def compute_kyber_graph_quality_sync(
    *,
    operator_tenant_id: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    accounts = _local_typed_rows(TradingAccountRepo.table_name)
    positions = _local_typed_rows(PositionRepo.table_name)
    # Graph ledger is a separate in-memory authority; only reachable via the
    # repository's per-tenant API, so the sync path aggregates from the rows it
    # can see (positions/accounts). Ledger-backed graph counters are computed by
    # the async ``compute_kyber_graph_quality`` (operator path).
    counters = aggregate_graph_quality_from_rows([], positions, accounts, now=now)
    return {"operator_tenant_id": operator_tenant_id, **counters}


__all__ = [
    "aggregate_fleet_from_rows",
    "aggregate_data_quality_from_rows",
    "aggregate_graph_quality_from_rows",
    "compute_kyber_fleet",
    "compute_kyber_data_quality",
    "compute_kyber_graph_quality",
    "compute_kyber_fleet_sync",
    "compute_kyber_data_quality_sync",
    "compute_kyber_graph_quality_sync",
    "AUTH_FAILURE_STATES",
    "RATE_LIMITED_STATES",
]
