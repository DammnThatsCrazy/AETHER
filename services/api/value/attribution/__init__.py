"""
Aether Service — Attribution
Multi-touch attribution modeling for cross-platform reward eligibility.
"""

from value.attribution.models import (
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
from value.attribution.resolver import AttributionConfig, AttributionResolver, JourneyStore

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
