"""Aether ML — Monitoring package. Re-exports key classes for convenient access."""

from monitoring.monitor import (
    DriftDetector,
    DriftResult,
    MonitoringPipeline,
    PerformanceMonitor,
)
from monitoring.alerts import (
    Alert,
    AlertManager,
    AlertSeverity,
    CloudWatchReporter,
    SlackAlerter,
    SNSAlerter,
)

__all__ = [
    "DriftDetector",
    "DriftResult",
    "MonitoringPipeline",
    "PerformanceMonitor",
    "Alert",
    "AlertManager",
    "AlertSeverity",
    "CloudWatchReporter",
    "SlackAlerter",
    "SNSAlerter",
]
