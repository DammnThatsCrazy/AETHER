"""Deterministic replay helpers for derivatives Bronze -> Silver -> position state."""
from __future__ import annotations

from services.derivatives.connectors.hyperliquid import HyperliquidConnector
from services.derivatives.models import BronzeObservation, PositionEpochState
from services.derivatives.position_engine import apply_fill


def replay_hyperliquid_fills(observations: list[BronzeObservation]) -> PositionEpochState | None:
    connector = HyperliquidConnector(tenant_id=observations[0].tenant_id if observations else "tenant")
    state: PositionEpochState | None = None
    for obs in sorted(observations, key=lambda item: (item.observed_at, item.source_record_id)):
        for fill in connector.normalize(obs):
            states = apply_fill(state, fill)
            state = states[-1]
    return state
