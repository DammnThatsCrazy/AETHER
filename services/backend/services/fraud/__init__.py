"""
Aether Service — Fraud Detection
Composable, weighted fraud scoring engine with modular signal detectors.
"""

from services.fraud.signals import (
    FraudSignal,
    SignalResult,
    BotDetectionSignal,
    SybilDetectionSignal,
    VelocitySignal,
    WalletAgeSignal,
    GeographicSignal,
    BehavioralSignal,
    DeviceFingerprintSignal,
    TransactionPatternSignal,
)
from services.fraud.engine import FraudConfig, FraudEngine, FraudResult

__all__ = [
    "FraudConfig",
    "FraudEngine",
    "FraudResult",
    "FraudSignal",
    "SignalResult",
    "BotDetectionSignal",
    "SybilDetectionSignal",
    "VelocitySignal",
    "WalletAgeSignal",
    "GeographicSignal",
    "BehavioralSignal",
    "DeviceFingerprintSignal",
    "TransactionPatternSignal",
]
