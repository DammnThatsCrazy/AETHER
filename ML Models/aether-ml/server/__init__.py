"""
Aether ML -- Server-side models for SageMaker/ECS deployment.

Re-exports all model classes for convenient top-level imports::

    from server import IdentityResolution, ChurnPrediction, LTVPrediction
    from server import AnomalyDetection, JourneyPrediction, CampaignAttribution
"""

from server.models import (
    AnomalyDetection,
    ChurnPrediction,
    IdentityResolution,
    LTVPrediction,
)
from server.journey_prediction import (
    AttentionLayer,
    JourneyDecoder,
    JourneyEncoder,
    JourneyPrediction,
)
from server.campaign_attribution import CampaignAttribution

__all__ = [
    # models.py
    "IdentityResolution",
    "ChurnPrediction",
    "LTVPrediction",
    "AnomalyDetection",
    # journey_prediction.py
    "JourneyEncoder",
    "AttentionLayer",
    "JourneyDecoder",
    "JourneyPrediction",
    # campaign_attribution.py
    "CampaignAttribution",
]
