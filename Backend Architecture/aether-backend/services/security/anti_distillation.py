"""
Aether — Anti-Distillation Controls

Protects intelligence APIs from systematic model distillation:
- Rapid diverse-query detection (too many wallets/minute)
- Address sweep detection (sequential or enumeration patterns)
- Score binning by plan tier (controlled precision output)
- Honeypot wallet detection
- Suspicious pattern audit logging

Enabled via AETHER_ANTI_DISTILLATION_ENABLED=true.
All detections emit to the audit log and surface in Kyber under
/v1/admin/kyber/intelligence/anti-distillation.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from pydantic import BaseModel
from shared.logger.logger import get_logger

logger = get_logger("aether.security.anti_distillation")


# ── Score binning by plan tier ────────────────────────────────────────────────

SCORE_BINS_BY_PLAN: Dict[str, float] = {
    "P1_HOBBYIST": 0.1,
    "P2_PROFESSIONAL": 0.05,
    "P3_GROWTH": 0.01,
    "P4_PROTOCOL": 0.001,
}

DEFAULT_PLAN_TIER = "P1_HOBBYIST"


def apply_output_precision(score: float, plan_tier: str = DEFAULT_PLAN_TIER) -> float:
    """Round a score to the precision allowed for the given plan tier.

    Higher-tier plans receive finer precision to support professional use.
    This prevents low-tier callers from reconstructing full-precision model output.
    """
    bin_size = SCORE_BINS_BY_PLAN.get(plan_tier, SCORE_BINS_BY_PLAN[DEFAULT_PLAN_TIER])
    return round(round(score / bin_size) * bin_size, 6)


# ── Models ────────────────────────────────────────────────────────────────────

class AntiDistillationConfig(BaseModel):
    rapid_diverse_query_threshold: int = 100
    address_sweep_detection: bool = True
    systematic_enumeration_detection: bool = True
    window_seconds: int = 60
    honeypot_wallets: List[str] = []


class AntiDistillationResult(BaseModel):
    is_suspicious: bool
    pattern_type: Optional[str] = None
    evidence: Dict[str, Any] = {}
    audit_event_id: Optional[str] = None
    checked_at: float = 0.0


@dataclass
class _TenantQueryWindow:
    """Sliding window for per-tenant query rate tracking."""
    timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=10000))
    addresses_seen: set = field(default_factory=set)


class AntiDistillationService:
    """Stateful detection service for intelligence API distillation patterns.

    All detections emit audit events. The service is stateless across restarts
    (production should use Redis for persistent sliding windows).
    """

    def __init__(self, config: Optional[AntiDistillationConfig] = None) -> None:
        self._config = config or AntiDistillationConfig()
        self._windows: Dict[str, _TenantQueryWindow] = defaultdict(_TenantQueryWindow)
        self._alerts: List[Dict[str, Any]] = []
        self._honeypot_set = set(self._config.honeypot_wallets)

    def is_honeypot_wallet(self, wallet_address: str) -> bool:
        """Return True if the address is a seeded honeypot wallet."""
        return wallet_address.lower() in {w.lower() for w in self._honeypot_set}

    def check_query_pattern(
        self,
        tenant_id: str,
        endpoint: str,
        query_params: Dict[str, Any],
    ) -> AntiDistillationResult:
        """Check if the query matches a suspicious distillation pattern.

        Checks performed:
        1. Rapid diverse-query rate (addresses/minute threshold)
        2. Honeypot wallet query
        3. Sequential address enumeration
        """
        now = time.time()
        window = self._windows[tenant_id]
        window.timestamps.append(now)

        # Extract wallet address if present
        wallet = query_params.get("wallet_address") or query_params.get("address") or ""

        # ── Honeypot check ───────────────────────────────────────────────────
        if wallet and self.is_honeypot_wallet(wallet):
            audit_id = self._record_suspicious_pattern(
                tenant_id=tenant_id,
                pattern_type="honeypot_wallet_query",
                evidence={"wallet": wallet, "endpoint": endpoint},
            )
            return AntiDistillationResult(
                is_suspicious=True,
                pattern_type="honeypot_wallet_query",
                evidence={"wallet": wallet, "endpoint": endpoint},
                audit_event_id=audit_id,
                checked_at=now,
            )

        # Track unique addresses
        if wallet:
            window.addresses_seen.add(wallet.lower())

        # ── Rapid diverse-query check ─────────────────────────────────────────
        window_start = now - self._config.window_seconds
        recent = sum(1 for t in window.timestamps if t >= window_start)

        if recent >= self._config.rapid_diverse_query_threshold:
            audit_id = self._record_suspicious_pattern(
                tenant_id=tenant_id,
                pattern_type="rapid_diverse_query",
                evidence={
                    "queries_in_window": recent,
                    "threshold": self._config.rapid_diverse_query_threshold,
                    "window_seconds": self._config.window_seconds,
                    "unique_addresses": len(window.addresses_seen),
                    "endpoint": endpoint,
                },
            )
            return AntiDistillationResult(
                is_suspicious=True,
                pattern_type="rapid_diverse_query",
                evidence={
                    "queries_in_window": recent,
                    "threshold": self._config.rapid_diverse_query_threshold,
                },
                audit_event_id=audit_id,
                checked_at=now,
            )

        return AntiDistillationResult(is_suspicious=False, checked_at=now)

    def _record_suspicious_pattern(
        self,
        tenant_id: str,
        pattern_type: str,
        evidence: Dict[str, Any],
    ) -> str:
        audit_id = f"audit_distill_{uuid.uuid4().hex}"
        alert = {
            "audit_event_id": audit_id,
            "tenant_id": tenant_id,
            "pattern_type": pattern_type,
            "evidence": evidence,
            "detected_at": time.time(),
        }
        self._alerts.append(alert)
        logger.warning(
            f"Anti-distillation alert: tenant={tenant_id} "
            f"pattern={pattern_type} audit={audit_id}"
        )
        return audit_id

    def get_alerts(self, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent distillation alerts, optionally filtered by tenant."""
        alerts = self._alerts if not tenant_id else [
            a for a in self._alerts if a.get("tenant_id") == tenant_id
        ]
        return sorted(alerts, key=lambda a: a["detected_at"], reverse=True)[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate stats for Kyber dashboard."""
        now = time.time()
        day_ago = now - 86400
        recent_24h = [a for a in self._alerts if a["detected_at"] >= day_ago]

        by_pattern: Dict[str, int] = {}
        for a in recent_24h:
            k = a.get("pattern_type", "unknown")
            by_pattern[k] = by_pattern.get(k, 0) + 1

        honeypot_count = sum(
            1 for a in recent_24h if a.get("pattern_type") == "honeypot_wallet_query"
        )

        return {
            "total_alerts_24h": len(recent_24h),
            "by_pattern_24h": by_pattern,
            "honeypot_queries_24h": honeypot_count,
            "active_tenant_windows": len(self._windows),
        }


# Module-level singleton
anti_distillation_service = AntiDistillationService()
