"""Tenant-scoped signal recomputation shared by API and identity restatement."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from repositories.repos import BehaviorProfileRepository, SignalRepository
from services.signals.signal_translator import (
    signals_from_asset_composition,
    signals_from_churn_model,
    signals_from_location_history,
)


async def recompute_signals_for_entity(
    entity_id: str,
    tenant_id: str,
    *,
    behavior_repo: Any | None = None,
    signal_repo: Any | None = None,
) -> dict[str, Any]:
    """Recompute signal records from the current tenant-owned behavior profile.

    Existing signal records are retained because this repository may contain
    signals from translators other than the behavior-profile translator. New
    records use deterministic IDs, so retries update the same generated signal.
    """
    behavior_repo = behavior_repo or BehaviorProfileRepository()
    signal_repo = signal_repo or SignalRepository()
    profile = await behavior_repo.find_by_id(entity_id)
    now = datetime.now(timezone.utc).isoformat()
    if profile is None or profile.get("tenant_id") != tenant_id:
        return {
            "entity_id": entity_id,
            "status": "completed",
            "signals_computed": 0,
            "computed_at": now,
        }

    generated: list[dict[str, Any]] = []
    churn_prob = profile.get("churn_probability", 0.0)
    features = {
        "days_since_last_visit": profile.get("days_since_last_visit", 0),
        "discount_usage_rate": profile.get("discount_usage_rate", 0.0),
        "referral_count": profile.get("referral_count", 0),
    }
    if churn_prob > 0:
        generated.extend(signals_from_churn_model(entity_id, features, churn_prob))

    stablecoin_pct = profile.get("stablecoin_pct", 0.0)
    altcoin_pct = profile.get("altcoin_pct", 0.0)
    top_symbol = profile.get("top_holding_symbol", "UNKNOWN")
    top_holding_pct = profile.get("top_holding_pct", 0.0)
    if stablecoin_pct > 0 or altcoin_pct > 0 or top_holding_pct > 0:
        generated.extend(signals_from_asset_composition(
            entity_id, stablecoin_pct, altcoin_pct, top_symbol, top_holding_pct
        ))

    locations = profile.get("location_history", [])
    if locations:
        generated.extend(signals_from_location_history(entity_id, locations))

    for sig in generated:
        signal_type = str(sig.get("signal_type", "SIG"))
        sig["tenant_id"] = tenant_id
        sig["entity_id"] = entity_id
        sig["signal_id"] = f"{signal_type}:{entity_id}:identity-restatement"
        sig["projection_source"] = "behavior_profile_translator"
        sig["created_at"] = now
        await signal_repo.upsert_signal(sig)

    current_generated_ids = {row["signal_id"] for row in generated}
    previous_rows = await signal_repo.list_for_entity(
        entity_id, tenant_id, include_stale=True, limit=1000
    )
    for row in previous_rows:
        if (
            row.get("projection_source") == "behavior_profile_translator"
            and row.get("signal_id") not in current_generated_ids
        ):
            await signal_repo.delete(row["signal_id"])

    return {
        "entity_id": entity_id,
        "status": "completed",
        "signals_computed": len(generated),
        "computed_at": now,
    }
