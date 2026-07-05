"""Stablecoin alert evaluator."""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Mapping, Any

class StablecoinAlertType(str, Enum):
    UNKNOWN_DEPLOYMENT = "unknown_deployment"
    PEG_DEVIATION = "peg_deviation"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    REORGANIZATION = "reorganization"
    FINALITY_DELAY = "finality_delay"
    DATA_QUALITY_FAILURE = "data_quality_failure"
    PROVIDER_DEGRADATION = "provider_degradation"
    SUPPORT_CHANGED = "support_changed"

class StablecoinAlertSeverity(str, Enum):
    INFO = "info"; WARNING = "warning"; CRITICAL = "critical"

@dataclass(frozen=True)
class StablecoinAlert:
    tenant_id: str
    alert_type: StablecoinAlertType
    severity: StablecoinAlertSeverity
    dedupe_key: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

class StablecoinAlertEvaluator:
    def evaluate_peg(self, *, tenant_id: str, deployment_id: str, peg_deviation_bps: Decimal, threshold_bps: Decimal = Decimal("50")) -> StablecoinAlert | None:
        if abs(peg_deviation_bps) < threshold_bps:
            return None
        severity = StablecoinAlertSeverity.CRITICAL if abs(peg_deviation_bps) >= Decimal("100") else StablecoinAlertSeverity.WARNING
        return StablecoinAlert(tenant_id, StablecoinAlertType.PEG_DEVIATION, severity, f"{tenant_id}:peg:{deployment_id}", "Stablecoin peg deviation crossed threshold", {"deployment_id": deployment_id, "peg_deviation_bps": str(peg_deviation_bps), "threshold_bps": str(threshold_bps)})

    def evaluate_reconciliation(self, *, tenant_id: str, payment_intent_id: str, state: str) -> StablecoinAlert | None:
        if state in {"matched", "pending_finality"}:
            return None
        return StablecoinAlert(tenant_id, StablecoinAlertType.RECONCILIATION_MISMATCH, StablecoinAlertSeverity.WARNING, f"{tenant_id}:reconciliation:{payment_intent_id}:{state}", "Stablecoin reconciliation requires review", {"payment_intent_id": payment_intent_id, "state": state})
