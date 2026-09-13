"""
Aether Service — Analytics Automation
Automated analytics pipeline for real-time campaign performance monitoring,
anomaly detection, and automated reward triggering.
"""

from services.analytics_automation.pipeline import (
    AnalyticsPipeline,
    AutomatedInsight,
    CampaignMetrics,
    EventClassifier,
    MetricWindow,
)

__all__ = [
    "AnalyticsPipeline",
    "AutomatedInsight",
    "CampaignMetrics",
    "EventClassifier",
    "MetricWindow",
]
