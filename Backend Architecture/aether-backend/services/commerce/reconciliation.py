"""
Aether Service — Commerce Lifecycle Reconciliation

Read-only reconciliation between the durable commerce control plane
(:mod:`services.x402.commerce_store`) and the Silver x402 flow facts
(``silver_x402_flow_facts``).

Entry points:
    rebuild_from_silver(tenant_id, from_time=None)
        Pull the tenant's Silver x402 flow facts and rebuild a normalized
        commerce-state snapshot (which challenges were observed, which paid,
        which settled).
    verify_graph_consistency(tenant_id)
        Check the commerce store's lifecycle objects for cross-reference
        integrity (settlement↔receipt, entitlement↔settlement, grant↔entitlement,
        fulfillment↔grant) and stale-state detection.
    reconciliation_drift(tenant_id)
        Diff Silver facts against the commerce store and return every detected
        inconsistency as a drift record. This is where "paid on-chain but never
        settled in the control plane" and "entitled but never granted" surface.
    reconcile_commerce(tenant_id)
        Full run: rebuild + verify + drift, returning one summary dict.

This module is read-only: it never mutates commerce state or Silver. The
supervised ``reconciliation`` worker builder (services/commerce/workers.py)
calls these and reports drift; remediation remains operator-driven.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from services.x402.commerce_store import get_commerce_store
from shared.logger.logger import get_logger

logger = get_logger("aether.service.commerce.reconciliation")

_SILVER_TABLE = "silver_x402_flow_facts"

# Meter-type ↔ silver flow-type mapping for drift detection.
_SILVER_PAID_FLOW_TYPES = frozenset({
    "x402_payment_verified_observed",
    "x402_resource_unlocked_observed",
    "x402_settlement_confirmed_observed",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Silver facts reader ─────────────────────────────────────────────────

class CommerceSilverFactsReader:
    """Reads ``silver_x402_flow_facts`` defensively across backends.

    Local/test: reads the silver writer's in-memory table store. Staging/prod:
    queries the columnar Silver table directly. Never raises on a missing
    table — returns an empty snapshot instead (the pipeline owns Silver).
    """

    async def read(self, tenant_id: str, from_time: Optional[str] = None) -> list[dict]:
        pool = await get_pool()
        if pool is None:
            return self._read_local(tenant_id, from_time)

        try:
            query = (
                f"SELECT * FROM {_SILVER_TABLE} "
                "WHERE tenant_id = $1"
            )
            params: list[Any] = [tenant_id]
            if from_time:
                query += " AND occurred_at >= $2"
                params.append(from_time)
            query += " ORDER BY occurred_at ASC LIMIT 10000"
            rows = await pool.fetch(query, *params)
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:  # pragma: no cover - depends on Silver pipeline
            logger.warning("silver facts read failed for tenant=%s: %s", tenant_id, exc)
            return []

    @staticmethod
    def _row_to_dict(row: Any) -> dict:
        try:
            return dict(row)
        except Exception:  # pragma: no cover
            return {}

    @staticmethod
    def _read_local(tenant_id: str, from_time: Optional[str]) -> list[dict]:
        try:
            from services.silver.writer import _local_tables
        except Exception:  # pragma: no cover
            return []
        table = _local_tables.get(_SILVER_TABLE, {})
        rows = [
            r for r in table.values()
            if (r.get("tenant_id") or "default") == tenant_id
        ]
        if from_time:
            rows = [r for r in rows if (r.get("occurred_at") or "") >= from_time]
        rows.sort(key=lambda r: r.get("occurred_at") or "")
        return rows


def _silver_fact_row_to_snapshot(row: dict) -> dict:
    """Normalize a silver row into a commerce-state snapshot entry."""
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    if isinstance(payload, dict):
        payload = {**payload}
    return {
        "source_event_id": row.get("source_event_id"),
        "flow_type": row.get("flow_type") or row.get("source_event_type"),
        "resource_id": row.get("resource_id") or payload.get("resourceId"),
        "settled": bool(row.get("settled")) or row.get("flow_type") in _SILVER_PAID_FLOW_TYPES,
        "amount": row.get("amount"),
        "currency": row.get("currency", "USD"),
        "settlement_tx_hash": row.get("settlement_tx_hash") or payload.get("settlementTxHash") or payload.get("txHash"),
        "occurred_at": row.get("occurred_at"),
    }


class CommerceReconciler:
    """Read-only commerce lifecycle reconciler."""

    def __init__(self) -> None:
        self._store = get_commerce_store()
        self._silver = CommerceSilverFactsReader()

    # ── Rebuild from Silver ──────────────────────────────────────────

    async def rebuild_from_silver(
        self, tenant_id: str, from_time: Optional[str] = None
    ) -> dict:
        """Rebuild a normalized commerce-state snapshot from Silver facts."""
        rows = await self._silver.read(tenant_id, from_time)
        facts = [_silver_fact_row_to_snapshot(r) for r in rows]
        return {
            "tenant_id": tenant_id,
            "facts": facts,
            "count": len(facts),
            "paid_count": sum(1 for f in facts if f["settled"]),
            "rebuilt_at": _now_iso(),
        }

    # ── Verify graph consistency ─────────────────────────────────────

    async def verify_graph_consistency(self, tenant_id: str) -> dict:
        """Verify cross-reference integrity across commerce lifecycle objects."""
        issues: list[dict] = []
        store = self._store

        receipts = await store.list_receipts(tenant_id)
        settlements = await store.list_settlements(tenant_id)
        entitlements = await store.list_entitlements(tenant_id)
        grants = await store.list_grants(tenant_id)
        fulfillments = await store.list_fulfillments(tenant_id)
        authorizations = await store.list_authorizations(tenant_id)

        receipt_ids = {r.receipt_id for r in receipts}
        settlement_ids = {s.settlement_id for s in settlements}
        entitlement_ids = {e.entitlement_id for e in entitlements}
        grant_ids = {g.grant_id for g in grants}

        # Every settlement must reference an existing receipt.
        for s in settlements:
            if s.receipt_id not in receipt_ids:
                issues.append({
                    "kind": "missing_receipt",
                    "severity": "critical",
                    "settlement_id": s.settlement_id,
                    "receipt_id": s.receipt_id,
                    "detail": "settlement references a receipt that does not exist",
                })
        # Every receipt should lead to a settlement (a paid receipt is settled).
        for r in receipts:
            if r.verified and not any(s.receipt_id == r.receipt_id for s in settlements):
                issues.append({
                    "kind": "unsettled_receipt",
                    "severity": "warning",
                    "receipt_id": r.receipt_id,
                    "challenge_id": r.challenge_id,
                    "detail": "verified receipt has no settlement",
                })
        # Every entitlement must reference an existing settlement.
        for e in entitlements:
            if e.settlement_id not in settlement_ids:
                issues.append({
                    "kind": "missing_settlement",
                    "severity": "critical",
                    "entitlement_id": e.entitlement_id,
                    "settlement_id": e.settlement_id,
                    "detail": "entitlement references a settlement that does not exist",
                })
        # Every grant must reference an existing entitlement.
        for g in grants:
            if g.entitlement_id not in entitlement_ids:
                issues.append({
                    "kind": "missing_entitlement",
                    "severity": "critical",
                    "grant_id": g.grant_id,
                    "entitlement_id": g.entitlement_id,
                    "detail": "grant references an entitlement that does not exist",
                })
        # Every fulfillment must reference an existing grant.
        for f in fulfillments:
            if f.grant_id not in grant_ids:
                issues.append({
                    "kind": "missing_grant",
                    "severity": "critical",
                    "fulfillment_id": f.fulfillment_id,
                    "grant_id": f.grant_id,
                    "detail": "fulfillment references a grant that does not exist",
                })
        # Stale entitlements (expired but still ACTIVE).
        now_iso = _now_iso()
        for e in entitlements:
            if e.status.value == "active" and e.expires_at and e.expires_at < now_iso:
                issues.append({
                    "kind": "stale_entitlement",
                    "severity": "warning",
                    "entitlement_id": e.entitlement_id,
                    "detail": "entitlement is expired but still ACTIVE",
                })

        return {
            "tenant_id": tenant_id,
            "verified": len(issues) == 0,
            "issue_count": len(issues),
            "issues": issues,
            "counts": {
                "authorizations": len(authorizations),
                "receipts": len(receipts),
                "settlements": len(settlements),
                "entitlements": len(entitlements),
                "grants": len(grants),
                "fulfillments": len(fulfillments),
            },
            "checked_at": _now_iso(),
        }

    # ── Drift: Silver vs store ───────────────────────────────────────

    async def reconciliation_drift(self, tenant_id: str) -> list[dict]:
        """Diff Silver facts against the commerce store; return drift records."""
        drift: list[dict] = []
        store = self._store

        # 1) Silver says paid, store has no settlement with that tx hash.
        silver = await self.rebuild_from_silver(tenant_id)
        settlements = await store.list_settlements(tenant_id)
        settled_tx_hashes = {
            (s.tx_hash or "").lower()
            for s in settlements
            if s.tx_hash
        }
        for fact in silver["facts"]:
            tx_hash = (fact.get("settlement_tx_hash") or "").lower()
            if fact["settled"] and tx_hash and tx_hash not in settled_tx_hashes:
                drift.append({
                    "kind": "silver_paid_not_settled",
                    "severity": "critical",
                    "resource_id": fact.get("resource_id"),
                    "settlement_tx_hash": fact.get("settlement_tx_hash"),
                    "source_event_id": fact.get("source_event_id"),
                    "detail": (
                        "Silver records a settled x402 payment whose settlement "
                        "tx hash is absent from the commerce store"
                    ),
                })

        # 2) Store has unsettled settlements (PENDING / VERIFYING that are old).
        for s in settlements:
            if s.state.value in ("pending", "verifying") and s.next_retry_at and s.next_retry_at < _now_iso():
                drift.append({
                    "kind": "stale_unsettled_settlement",
                    "severity": "warning",
                    "settlement_id": s.settlement_id,
                    "challenge_id": s.challenge_id,
                    "detail": "settlement stuck in non-terminal state past its retry window",
                })

        # 3) Store has verified receipts but no matching Silver paid fact.
        receipts = await store.list_receipts(tenant_id)
        silver_tx_hashes = {
            (f.get("settlement_tx_hash") or "").lower()
            for f in silver["facts"]
            if f.get("settlement_tx_hash")
        }
        for r in receipts:
            if r.verified and (r.tx_hash or "").lower() not in silver_tx_hashes:
                drift.append({
                    "kind": "paid_but_no_silver_fact",
                    "severity": "warning",
                    "receipt_id": r.receipt_id,
                    "challenge_id": r.challenge_id,
                    "tx_hash": r.tx_hash,
                    "detail": "verified receipt in the store has no matching Silver flow fact",
                })

        return drift

    # ── Full reconcile ───────────────────────────────────────────────

    async def reconcile_commerce(self, tenant_id: str) -> dict:
        """Full reconciliation run for one tenant (read-only)."""
        rebuilt = await self.rebuild_from_silver(tenant_id)
        consistency = await self.verify_graph_consistency(tenant_id)
        drift = await self.reconciliation_drift(tenant_id)
        return {
            "tenant_id": tenant_id,
            "rebuilt_from_silver": rebuilt,
            "graph_consistency": consistency,
            "drift": drift,
            "drift_count": len(drift),
            "reconciled_at": _now_iso(),
        }


# ── Module-level helpers / singleton ────────────────────────────────────

_reconciler: Optional[CommerceReconciler] = None


def get_commerce_reconciler() -> CommerceReconciler:
    global _reconciler
    if _reconciler is None:
        _reconciler = CommerceReconciler()
    return _reconciler


def reset_commerce_reconciler() -> None:
    """Reset the reconciler — for tests only."""
    global _reconciler
    _reconciler = None


__all__ = [
    "CommerceReconciler",
    "CommerceSilverFactsReader",
    "get_commerce_reconciler",
    "reset_commerce_reconciler",
]
