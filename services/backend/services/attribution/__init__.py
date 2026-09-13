"""
Aether Service — Attribution
Multi-touch attribution modeling for cross-platform reward eligibility.
"""

from services.attribution.models import (
    AttributionModel,
    AttributionResult,
    DataDrivenModel,
    FirstTouchModel,
    LastTouchModel,
    LinearModel,
    PositionBasedModel,
    TimeDecayModel,
    Touchpoint,
)
from services.attribution.resolver import AttributionConfig, AttributionResolver, JourneyStore

__all__ = [
    "AttributionConfig",
    "AttributionModel",
    "AttributionResolver",
    "AttributionResult",
    "DataDrivenModel",
    "FirstTouchModel",
    "JourneyStore",
    "LastTouchModel",
    "LinearModel",
    "PositionBasedModel",
    "TimeDecayModel",
    "Touchpoint",
]
