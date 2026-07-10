"""Stablecoin Intelligence ↔ Suggestion adapter.

Maps observed depeg valuation snapshots to OODA suggestions. Suggestions
only — Aether never executes trades, rebalances, or on-chain actions in
response. Gated by settings.suggestions.stablecoin_adapter_enabled.
"""

from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.stablecoin")

_DEPEG_STATUSES = frozenset({"depegged", "minor_deviation"})


def create_suggestion_from_depeg_snapshot(
    snapshot: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map a stablecoin valuation snapshot to a SuggestionCreate.

    Returns None unless the snapshot's peg_status is a depeg signal.
    Idempotency basis: the snapshot id (source_ref + lineage).
    """
    peg_status = str(snapshot.get("peg_status", "")).lower()
    if peg_status not in _DEPEG_STATUSES:
        return None

    snapshot_id = snapshot.get("valuation_id") or snapshot.get("id", "")
    asset_id = (
        snapshot.get("canonical_asset_id")
        or snapshot.get("deployment_id")
        or "unknown"
    )
    deviation = snapshot.get("peg_deviation_bps")
    confirmed = peg_status == "depegged"

    deviation_text = f" (deviation {deviation} bps)" if deviation is not None else ""

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(kind="entity", id=asset_id),
        source=SuggestionSource.RULE,
        source_ref={"service": "stablecoin_intelligence", "id": snapshot_id},
        suggestion_class=SuggestionClass.STABLECOIN_DEPEG,
        title=f"Stablecoin peg deviation observed: {asset_id}",
        summary=f"{asset_id} peg status is '{peg_status}'{deviation_text}",
        what=(
            f"A valuation snapshot recorded peg status '{peg_status}' for "
            f"{asset_id}{deviation_text}."
        ),
        why=(
            "Observed market price crossed the configured depeg threshold. "
            "This is an observation of external market state, not an action "
            "taken by Aether."
        ),
        impact=(
            "Tenant exposure denominated in this asset may be mispriced; "
            "flows and valuations referencing it should be reviewed."
        ),
        recommended_action=(
            "Review the asset's valuation history and exposure, and confirm "
            "the deviation against independent price sources."
        ),
        confidence_score=0.9 if confirmed else 0.7,
        risk_score=0.8 if confirmed else 0.5,
        reversible=True,
        evidence=[
            {
                "id": snapshot_id,
                "type": "valuation_snapshot",
                "source": "stablecoin_intelligence",
                "observedAt": snapshot.get("observed_at") or utc_now().isoformat(),
                "confidence": 0.9 if confirmed else 0.7,
            }
        ],
        lineage_event_ids=[snapshot_id] if snapshot_id else [],
    )
