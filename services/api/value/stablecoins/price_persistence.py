"""Stablecoin price-observation write path + multi-provider disagreement reconcile.

Closes the Phase-0 gap for the stablecoin price domain: the
``StablecoinChainlinkPriceConnector`` produced price observations but nothing
persisted them by default (the sink required explicit wiring + ``emit=True``),
and multi-provider disagreement was detected in-memory but never written to the
durable reconciliation store.

This module provides:

  * :func:`persist_price_observation` — run one connector read and persist the
    resulting snapshot through the connector's own persistence seam (a default
    ``StablecoinPriceObservationSink`` is wired when the connector has none). An
    UNAVAILABLE snapshot is persisted exactly as observed — the price is never
    fabricated as 0/1 USD.
  * :class:`StablecoinPriceReconciler` — reconcile a set of same-deployment
    snapshots from different feeds and persist the verdict to
    ``stablecoin_reconciliation_results``. Re-reconciling the exact same
    snapshot set yields the ``duplicate`` state (idempotent replay, never a
    double-counted conflict); genuine multi-provider disagreement yields the
    ``conflict`` state with the offending providers and spread in basis points.
    The replay signature hashes the observed prices + timestamps (the snapshot
    payload), so a genuinely new snapshot — a new price, spread, or observation
    time — is a new signature and a fresh conflict, never a stale duplicate.

Observation-only: nothing here signs, sends, or mutates on-chain state.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from repositories.stablecoin_repos import StablecoinReconciliationRepository
from shared.common.common import utc_now

from .price_feed import (
    CONFLICT_STATE,
    PRICE_UNAVAILABLE_STATE,
    StablecoinChainlinkPriceConnector,
    StablecoinPriceConflictDetector,
    StablecoinPriceObservation,
    StablecoinPriceObservationSink,
)

#: Reconciliation states persisted by the price reconciler. ``duplicate`` mirrors
#: the stablecoin domain's replay guard: the same snapshot set reconciled twice
#: must not produce a second conflict row.
STATE_DUPLICATE = "duplicate"


async def persist_price_observation(
    connector: StablecoinChainlinkPriceConnector,
    *,
    tenant_id: str,
    sink: Optional[StablecoinPriceObservationSink] = None,
) -> StablecoinPriceObservation:
    """Fetch + durably persist one price snapshot through the connector path.

    When the connector was not constructed with a sink (or ``emit=False``), a
    default JSONB sink is attached and the snapshot is emitted immediately, so a
    production caller gets a durable record without remembering to wire the
    seam. Returns the snapshot (unchanged by persistence — a sink failure never
    alters the honest availability/price semantics).
    """
    if connector.sink is None:
        connector.sink = sink or StablecoinPriceObservationSink()
        connector.emit_enabled = True
    elif not connector.emit_enabled:
        connector.emit_enabled = True
    snapshot = await connector.get_price_observation(tenant_id=tenant_id)
    # Defensive emit: a connector that yields a snapshot without an emit path
    # still gets a durable record. The sink is idempotent on the snapshot
    # identity, so re-emitting an already-persisted snapshot collapses.
    if connector.sink is not None:
        try:
            await connector.sink.persist_snapshot(snapshot, tenant_id=tenant_id)
        except Exception:  # noqa: BLE001 — fail-open, value unchanged
            pass
    return snapshot


class StablecoinPriceReconciler:
    """Persist multi-provider price agreement/disagreement verdicts durably."""

    def __init__(
        self,
        detector: Optional[StablecoinPriceConflictDetector] = None,
        repo: Optional[StablecoinReconciliationRepository] = None,
    ) -> None:
        self.detector = detector or StablecoinPriceConflictDetector()
        self.repo = repo or StablecoinReconciliationRepository()

    @staticmethod
    def _signature(
        tenant_id: str,
        deployment_id: str,
        snapshots: list[StablecoinPriceObservation],
        state: str,
    ) -> str:
        """Deterministic fingerprint of one reconciliation verdict.

        Hashes the observed snapshot payloads (per-provider price + observed_at)
        alongside tenant / deployment / provider / state so a genuinely NEW
        snapshot — a new price, a new spread, or a new observation time —
        yields a new signature and a real conflict record, while a true replay
        of the identical snapshot set still collapses to ``duplicate``.
        Providers are sorted and each snapshot serialized stably, so the
        fingerprint is order-independent.
        """
        providers = ",".join(sorted(s.provider for s in snapshots))
        payload = ";".join(
            "|".join([
                s.provider,
                str(s.price_usd) if s.price_usd is not None else "",
                str(s.observed_at),
            ])
            for s in sorted(
                snapshots, key=lambda s: (s.provider, str(s.observed_at))
            )
        )
        raw = "|".join([
            tenant_id or "",
            deployment_id or "",
            providers,
            state,
            payload,
        ])
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def reconcile(
        self,
        tenant_id: str,
        snapshots: list[StablecoinPriceObservation],
    ) -> dict[str, Any]:
        """Classify a snapshot set and persist the verdict durably.

        Returns the persisted (or previously-persisted) reconciliation record.
        Idempotent: the SAME snapshot set (tenant, deployment, providers, the
        observed prices + timestamps) reconciled twice resolves to
        ``duplicate`` — never a second conflict row. A genuinely new snapshot
        (new price / spread / observation time) is a NEW signature and a real
        conflict, not a stale duplicate.
        """
        if not snapshots:
            raise ValueError("reconcile requires at least one price snapshot")
        if not tenant_id:
            raise ValueError("tenant_id is required to reconcile price snapshots")

        verdict = self.detector.detect(snapshots)
        deployment_id = verdict.deployment_id or snapshots[0].deployment_id
        providers = verdict.providers or tuple(s.provider for s in snapshots)
        state = verdict.state

        # Replay guard: the signature hashes the observed prices + timestamps,
        # so only a TRUE replay of the identical snapshot set dedupes; a new
        # price / spread / observation time produces a fresh signature.
        sig = self._signature(tenant_id, deployment_id, snapshots, state)
        existing = await self.repo.find_many(
            filters={"tenant_id": tenant_id, "signature": sig}, limit=1,
        )
        if existing:
            return {
                "reconciliation_id": existing[0]["reconciliation_id"],
                "tenant_id": tenant_id,
                "deployment_id": deployment_id,
                "state": STATE_DUPLICATE,
                "reason": "price snapshot set already reconciled",
                "providers": providers,
                "prices": verdict.prices,
                "duplicate_of": existing[0]["reconciliation_id"],
            }

        observed_at = max((s.observed_at for s in snapshots if s.observed_at), default=utc_now().isoformat())
        reconciliation_id = f"stablecoin_price_reconciled:{tenant_id}:{deployment_id}:{sig}"
        record = {
            "reconciliation_id": reconciliation_id,
            "tenant_id": tenant_id,
            "deployment_id": deployment_id,
            "state": state,
            "reason": verdict.reason,
            "providers": list(providers),
            "prices": [str(p) if p is not None else None for p in verdict.prices],
            "threshold_bps": str(self.detector.threshold_bps),
            "signature": sig,
            "observed_at": observed_at,
            "evidence": {
                "providers": list(providers),
                "prices": [str(p) if p is not None else None for p in verdict.prices],
                "reason": verdict.reason,
            },
            "created_at": utc_now().isoformat(),
        }
        await self.repo.insert(reconciliation_id, record)
        return {
            "reconciliation_id": reconciliation_id,
            "tenant_id": tenant_id,
            "deployment_id": deployment_id,
            "state": state,
            "reason": verdict.reason,
            "providers": providers,
            "prices": verdict.prices,
        }

    @staticmethod
    def is_conflict(state: str) -> bool:
        return state == CONFLICT_STATE

    @staticmethod
    def is_unavailable(state: str) -> bool:
        return state == PRICE_UNAVAILABLE_STATE


__all__ = [
    "persist_price_observation",
    "StablecoinPriceReconciler",
    "STATE_DUPLICATE",
]
