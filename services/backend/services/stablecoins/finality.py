"""Stablecoin finality and reorganization handling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repositories.stablecoin_repos import StablecoinObservationRepository
from shared.common.common import utc_now

from .models import FinalityState

_ALLOWED: dict[FinalityState, set[FinalityState]] = {
    FinalityState.OBSERVED: {FinalityState.PENDING, FinalityState.CONFIRMED, FinalityState.FAILED, FinalityState.UNKNOWN},
    FinalityState.PENDING: {FinalityState.CONFIRMED, FinalityState.FAILED, FinalityState.DROPPED, FinalityState.UNKNOWN},
    FinalityState.CONFIRMED: {FinalityState.FINALIZED, FinalityState.REVERTED, FinalityState.DISPUTED, FinalityState.UNKNOWN},
    FinalityState.FINALIZED: {FinalityState.REVERTED, FinalityState.DISPUTED},
    FinalityState.REVERTED: set(),
    FinalityState.DROPPED: set(),
    FinalityState.FAILED: set(),
    FinalityState.DISPUTED: {FinalityState.FINALIZED, FinalityState.REVERTED},
    FinalityState.UNKNOWN: {FinalityState.PENDING, FinalityState.CONFIRMED, FinalityState.FAILED, FinalityState.DROPPED},
}


@dataclass(frozen=True)
class FinalityTransition:
    observation_id: str
    previous_state: FinalityState
    new_state: FinalityState
    reason: str
    correction_event: str | None
    occurred_at: str


class StablecoinFinalityService:
    def __init__(self, observations: StablecoinObservationRepository | None = None) -> None:
        self.observations = observations or StablecoinObservationRepository()

    async def transition(self, observation_id: str, new_state: FinalityState, *, reason: str) -> FinalityTransition:
        record = await self.observations.find_by_id(observation_id)
        if not record:
            raise ValueError(f"stablecoin observation not found: {observation_id}")
        previous = FinalityState(record.get("finality_status", FinalityState.UNKNOWN.value))
        if new_state != previous and new_state not in _ALLOWED[previous]:
            raise ValueError(f"invalid finality transition {previous.value}->{new_state.value}")
        history = list(record.get("finality_history", []))
        now = utc_now().isoformat()
        history.append({"from": previous.value, "to": new_state.value, "reason": reason, "at": now})
        record["finality_status"] = new_state.value
        record["finality_history"] = history
        if new_state == FinalityState.FINALIZED:
            record["finalized_at"] = now
        if new_state == FinalityState.REVERTED:
            record["reverted_at"] = now
            record["requires_downstream_correction"] = True
        await self.observations.update(observation_id, record)
        correction = "stablecoin.transaction.reverted" if new_state == FinalityState.REVERTED else None
        return FinalityTransition(observation_id, previous, new_state, reason, correction, now)
