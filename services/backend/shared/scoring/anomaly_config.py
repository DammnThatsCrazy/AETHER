"""
Aether Shared — Anomaly Detection Config Extension
Extends the existing Anomaly Detection model's INPUT FEATURES, not the model itself.
The IsolationForest + Autoencoder model is NOT retrained.

These config entries define new feature columns that get appended to the
model's input DataFrame when Intelligence Graph layers are enabled.

Used by: ML Serving service, Anomaly Detection pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════
# ANOMALY CLASS DEFINITION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AnomalyClassConfig:
    """Configuration for a single anomaly detection class."""
    name: str
    feature: str
    description: str
    threshold: Optional[float] = None
    threshold_sigma: Optional[float] = None
    layer: str = "A2A"  # Which relationship layer this class applies to


# ═══════════════════════════════════════════════════════════════════════════
# EXTENDED ANOMALY CLASSES (Intelligence Graph)
# ═══════════════════════════════════════════════════════════════════════════

EXTENDED_ANOMALY_CLASSES: list[AnomalyClassConfig] = [
    AnomalyClassConfig(
        name="agent_velocity_spike",
        feature="agent_events_per_minute",
        description="Agent generating events faster than expected",
        threshold=100,
        layer="A2A",
    ),
    AnomalyClassConfig(
        name="agent_spend_anomaly",
        feature="agent_hourly_spend_usd",
        description="Agent spending significantly more than historical average",
        threshold_sigma=3,
        layer="A2A",
    ),
    AnomalyClassConfig(
        name="contract_interaction_burst",
        feature="contract_calls_per_hour",
        description="Unusual burst of smart contract interactions",
        threshold=500,
        layer="A2A",
    ),
    AnomalyClassConfig(
        name="cross_agent_collusion",
        feature="shared_wallet_agent_count",
        description="Multiple agents sharing same wallet (potential collusion)",
        threshold=5,
        layer="A2A",
    ),
    AnomalyClassConfig(
        name="x402_payment_anomaly",
        feature="x402_amount_zscore",
        description="x402 payment amount deviating from expected range",
        threshold_sigma=3,
        layer="A2A",
    ),
    AnomalyClassConfig(
        name="bytecode_risk_trigger",
        feature="bytecode_risk_score",
        description="Contract bytecode matches known risk patterns",
        threshold=0.7,
        layer="A2A",
    ),
]


def get_extended_feature_columns() -> list[str]:
    """Return the list of new feature column names for the anomaly model."""
    return [ac.feature for ac in EXTENDED_ANOMALY_CLASSES]


def get_threshold_config() -> dict[str, dict]:
    """Return threshold configuration for each anomaly class."""
    config = {}
    for ac in EXTENDED_ANOMALY_CLASSES:
        entry: dict = {"feature": ac.feature, "layer": ac.layer}
        if ac.threshold is not None:
            entry["threshold"] = ac.threshold
        if ac.threshold_sigma is not None:
            entry["threshold_sigma"] = ac.threshold_sigma
        config[ac.name] = entry
    return config
