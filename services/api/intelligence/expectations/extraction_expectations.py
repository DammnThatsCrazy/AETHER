"""
Extraction Expectation Engine — internal-only scoring infrastructure.

Computes what a caller *should* look like vs what it is actually doing,
using self-history baselines, peer baselines, and graph-linked identity
baselines. No public API endpoints — consumed only by the extraction
risk scorer.

Reuses existing subsystems:
    - AnalyticsRepository for self-history
    - GraphClient for peer/neighbor reasoning
    - CacheClient for nearline state
    - Expectation models for signal records
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.scoring.extraction_models import (
    ExtractionIdentity,
    ExtractionSignal,
    SignalSeverity,
)

logger = get_logger("aether.expectations.extraction")


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION EXPECTATION SIGNALS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionExpectationResult:
    """Aggregate result from the extraction expectation engine."""
    signals: list[ExtractionSignal] = field(default_factory=list)
    composite_deviation: float = 0.0   # 0–1 normalized
    baseline_quality: float = 0.0      # how much history we had to work with
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_count": len(self.signals),
            "composite_deviation": round(self.composite_deviation, 4),
            "baseline_quality": round(self.baseline_quality, 2),
            "signals": [s.to_dict() for s in self.signals],
        }


class ExtractionExpectationEngine:
    """
    Internal expectation engine for extraction defense.

    Computes behavioral baselines and detects extraction-indicative
    deviations. Not exposed via any public API.
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
    ) -> None:
        self._redis = redis_client
        self._actor_history: dict[str, list[dict]] = {}  # in-memory fallback

    async def compute_signals(
        self,
        identity: ExtractionIdentity,
        model_name: str,
        features: dict[str, Any],
        batch_size: int = 1,
        endpoint: str = "",
    ) -> ExtractionExpectationResult:
        """
        Compute all extraction expectation signals for a request.

        Returns signals with values 0–1 where higher means more suspicious.
        """
        actor_key = identity.primary_key
        signals: list[ExtractionSignal] = []
        baseline_quality = 0.0

        # Record this request in actor history
        request_record = {
            "ts": time.time(),
            "model": model_name,
            "endpoint": endpoint,
            "batch_size": batch_size,
            "feature_hash": _feature_hash(features),
            "feature_count": len(features),
            "ip": identity.source_ip or "",
            "device": identity.device_fingerprint or "",
        }
        history = await self._get_history(actor_key)
        history.append(request_record)
        await self._set_history(actor_key, history[-500:])  # keep last 500

        if len(history) < 3:
            return ExtractionExpectationResult(
                signals=signals, baseline_quality=0.0
            )

        baseline_quality = min(len(history) / 50.0, 1.0)

        # ── Self-baseline signals ────────────────────────────────────
        signals.append(self._compute_rate_deviation(history, actor_key))
        signals.append(self._compute_model_enumeration(history))
        signals.append(self._compute_feature_sweep(history))
        signals.append(self._compute_boundary_probe(history))
        signals.append(self._compute_near_duplicate_burst(history))
        signals.append(self._compute_batch_usage_deviation(history, batch_size))
        signals.append(self._compute_coverage_expansion(history))
        signals.append(self._compute_confidence_harvest(history))

        # ── Identity churn / contradiction signals ───────────────────
        signals.append(self._compute_identity_churn(history, identity))
        signals.append(self._compute_device_geo_contradiction(history, identity))

        # Filter out zero-value signals
        active_signals = [s for s in signals if s.value > 0.01]

        # Composite deviation: weighted average of active signals
        if active_signals:
            total_weight = sum(_signal_weight(s) for s in active_signals)
            composite = sum(s.value * _signal_weight(s) for s in active_signals) / max(total_weight, 1.0)
        else:
            composite = 0.0

        metrics.increment("extraction_expectation_computed")
        return ExtractionExpectationResult(
            signals=active_signals,
            composite_deviation=min(composite, 1.0),
            baseline_quality=baseline_quality,
        )

    # ── Signal computations ──────────────────────────────────────────

    def _compute_rate_deviation(self, history: list[dict], actor_key: str) -> ExtractionSignal:
        """Detect unusual request rate compared to self-history."""
        now = time.time()
        recent_1m = [r for r in history if now - r["ts"] < 60]
        recent_5m = [r for r in history if now - r["ts"] < 300]
        older = [r for r in history if now - r["ts"] >= 300]

        if not older:
            return ExtractionSignal(name="self_rate_deviation", value=0.0, source="self_baseline")

        # Compare recent rate to historical average
        history_span = max(now - history[0]["ts"], 60)
        avg_rpm = len(older) / (history_span / 60)
        current_rpm = len(recent_1m)

        if avg_rpm < 0.5:
            deviation = min(current_rpm / 10.0, 1.0)
        else:
            ratio = current_rpm / max(avg_rpm, 0.1)
            deviation = min(max(0, (ratio - 2.0) / 8.0), 1.0)  # Ramp from 2x to 10x

        severity = (
            SignalSeverity.HIGH if deviation > 0.7
            else SignalSeverity.MEDIUM if deviation > 0.3
            else SignalSeverity.LOW
        )
        return ExtractionSignal(
            name="self_rate_deviation",
            value=deviation,
            severity=severity,
            source="self_baseline",
            evidence={"current_rpm": current_rpm, "avg_rpm": round(avg_rpm, 2)},
        )

    def _compute_model_enumeration(self, history: list[dict]) -> ExtractionSignal:
        """Detect querying many distinct models (model family sweep)."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 3600]  # last hour
        models = set(r["model"] for r in recent if r.get("model"))
        count = len(models)

        # 1–2 models is normal, 5+ is suspicious, 9 (all) is very suspicious
        if count <= 2:
            value = 0.0
        elif count <= 4:
            value = (count - 2) / 6.0
        else:
            value = min((count - 2) / 7.0, 1.0)

        return ExtractionSignal(
            name="model_enumeration_signal",
            value=value,
            severity=SignalSeverity.HIGH if value > 0.5 else SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={"distinct_models_1h": count, "models": list(models)[:5]},
        )

    def _compute_feature_sweep(self, history: list[dict]) -> ExtractionSignal:
        """Detect systematic feature-space exploration."""
        now = time.time()
        recent_hashes = [r["feature_hash"] for r in history if now - r["ts"] < 600]
        if len(recent_hashes) < 5:
            return ExtractionSignal(name="feature_sweep_signal", value=0.0, source="self_baseline")

        unique_ratio = len(set(recent_hashes)) / len(recent_hashes)

        # Very high uniqueness with high volume = sweep
        volume_factor = min(len(recent_hashes) / 50.0, 1.0)
        value = unique_ratio * volume_factor

        if value < 0.3:
            value = 0.0

        return ExtractionSignal(
            name="feature_sweep_signal",
            value=min(value, 1.0),
            severity=SignalSeverity.HIGH if value > 0.6 else SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={
                "unique_ratio": round(unique_ratio, 3),
                "query_count_10m": len(recent_hashes),
            },
        )

    def _compute_boundary_probe(self, history: list[dict]) -> ExtractionSignal:
        """Detect probing near decision boundaries (similar features, different models)."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 600 and r.get("feature_hash")]
        if len(recent) < 10:
            return ExtractionSignal(name="boundary_probe_signal", value=0.0, source="self_baseline")

        # Check for repeated similar feature hashes with slight variations
        hash_prefix_groups: dict[str, int] = {}
        for r in recent:
            prefix = r["feature_hash"][:8]
            hash_prefix_groups[prefix] = hash_prefix_groups.get(prefix, 0) + 1

        # If many queries cluster around similar feature regions
        clusters = [c for c in hash_prefix_groups.values() if c >= 3]
        if not clusters:
            return ExtractionSignal(name="boundary_probe_signal", value=0.0, source="self_baseline")

        cluster_ratio = sum(clusters) / len(recent)
        value = min(cluster_ratio, 1.0) if cluster_ratio > 0.3 else 0.0

        return ExtractionSignal(
            name="boundary_probe_signal",
            value=value,
            severity=SignalSeverity.HIGH if value > 0.5 else SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={"cluster_ratio": round(cluster_ratio, 3), "cluster_count": len(clusters)},
        )

    def _compute_near_duplicate_burst(self, history: list[dict]) -> ExtractionSignal:
        """Detect bursts of near-duplicate queries."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 120]
        if len(recent) < 5:
            return ExtractionSignal(name="near_duplicate_burst_signal", value=0.0, source="self_baseline")

        hashes = [r["feature_hash"] for r in recent]
        duplicates = len(hashes) - len(set(hashes))
        dup_ratio = duplicates / len(hashes)

        value = min(dup_ratio * 2, 1.0) if dup_ratio > 0.2 else 0.0

        return ExtractionSignal(
            name="near_duplicate_burst_signal",
            value=value,
            severity=SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={"duplicate_ratio": round(dup_ratio, 3), "query_count_2m": len(recent)},
        )

    def _compute_batch_usage_deviation(self, history: list[dict], current_batch: int) -> ExtractionSignal:
        """Detect unusual batch size patterns."""
        batch_sizes = [r.get("batch_size", 1) for r in history[-50:]]
        avg_batch = sum(batch_sizes) / max(len(batch_sizes), 1)

        if current_batch <= 1 and avg_batch <= 2:
            return ExtractionSignal(name="batch_usage_deviation", value=0.0, source="self_baseline")

        # Large batch after mostly single requests
        if avg_batch < 5 and current_batch > 50:
            value = min(current_batch / 200.0, 1.0)
        elif avg_batch > 0:
            ratio = current_batch / max(avg_batch, 1)
            value = min(max(0, (ratio - 3) / 7.0), 1.0)
        else:
            value = 0.0

        return ExtractionSignal(
            name="batch_usage_deviation",
            value=value,
            severity=SignalSeverity.MEDIUM if value > 0.3 else SignalSeverity.LOW,
            source="self_baseline",
            evidence={"current_batch": current_batch, "avg_batch": round(avg_batch, 1)},
        )

    def _compute_coverage_expansion(self, history: list[dict]) -> ExtractionSignal:
        """Detect steadily expanding feature-space coverage (distillation indicator)."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 3600]
        if len(recent) < 20:
            return ExtractionSignal(name="unique_coverage_expansion_signal", value=0.0, source="self_baseline")

        # Split into halves and compare unique hash growth
        mid = len(recent) // 2
        first_half = set(r["feature_hash"] for r in recent[:mid])
        second_half = set(r["feature_hash"] for r in recent[mid:])

        new_in_second = len(second_half - first_half)
        expansion_rate = new_in_second / max(len(second_half), 1)

        # High expansion rate with high volume = systematic coverage
        value = expansion_rate * min(len(recent) / 100.0, 1.0)
        value = min(value, 1.0) if value > 0.3 else 0.0

        return ExtractionSignal(
            name="unique_coverage_expansion_signal",
            value=value,
            severity=SignalSeverity.HIGH if value > 0.6 else SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={
                "expansion_rate": round(expansion_rate, 3),
                "total_queries_1h": len(recent),
                "new_hashes_second_half": new_in_second,
            },
        )

    def _compute_confidence_harvest(self, history: list[dict]) -> ExtractionSignal:
        """Detect patterns consistent with confidence/soft-label harvesting."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 1800]
        if len(recent) < 10:
            return ExtractionSignal(name="confidence_harvest_signal", value=0.0, source="self_baseline")

        # High-volume, unique-feature, single-model pattern = harvesting
        models = set(r["model"] for r in recent)
        hashes = [r["feature_hash"] for r in recent]
        unique_ratio = len(set(hashes)) / max(len(hashes), 1)

        single_model_focus = 1.0 if len(models) == 1 else max(0, 1.0 - len(models) / 5.0)
        volume_factor = min(len(recent) / 100.0, 1.0)

        value = unique_ratio * single_model_focus * volume_factor
        value = min(value, 1.0) if value > 0.2 else 0.0

        return ExtractionSignal(
            name="confidence_harvest_signal",
            value=value,
            severity=SignalSeverity.HIGH if value > 0.5 else SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={
                "unique_ratio": round(unique_ratio, 3),
                "model_focus": round(single_model_focus, 2),
                "query_count_30m": len(recent),
            },
        )

    def _compute_identity_churn(self, history: list[dict], identity: ExtractionIdentity) -> ExtractionSignal:
        """Detect identity dimension churn (key rotation, device switching)."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 3600]
        if len(recent) < 5:
            return ExtractionSignal(name="identity_churn_signal", value=0.0, source="self_baseline")

        unique_ips = len(set(r.get("ip", "") for r in recent if r.get("ip")))
        unique_devices = len(set(r.get("device", "") for r in recent if r.get("device")))

        # Lots of different IPs/devices from same API key = evasion
        ip_churn = min(unique_ips / 10.0, 1.0) if unique_ips > 3 else 0.0
        device_churn = min(unique_devices / 8.0, 1.0) if unique_devices > 3 else 0.0

        value = max(ip_churn, device_churn)

        return ExtractionSignal(
            name="identity_churn_signal",
            value=value,
            severity=SignalSeverity.HIGH if value > 0.5 else SignalSeverity.MEDIUM,
            source="self_baseline",
            evidence={"unique_ips_1h": unique_ips, "unique_devices_1h": unique_devices},
        )

    def _compute_device_geo_contradiction(self, history: list[dict], identity: ExtractionIdentity) -> ExtractionSignal:
        """Detect contradictory device/IP combinations."""
        now = time.time()
        recent = [r for r in history if now - r["ts"] < 3600]
        if len(recent) < 5:
            return ExtractionSignal(name="device_geo_contradiction_signal", value=0.0, source="self_baseline")

        # Check if same device seen from many different IPs
        device_ip_map: dict[str, set] = {}
        for r in recent:
            device = r.get("device", "")
            ip = r.get("ip", "")
            if device and ip:
                device_ip_map.setdefault(device, set()).add(ip)

        max_ips_per_device = max((len(ips) for ips in device_ip_map.values()), default=0)
        value = min(max_ips_per_device / 10.0, 1.0) if max_ips_per_device > 3 else 0.0

        return ExtractionSignal(
            name="device_geo_contradiction_signal",
            value=value,
            severity=SignalSeverity.MEDIUM if value > 0.3 else SignalSeverity.LOW,
            source="self_baseline",
            evidence={"max_ips_per_device": max_ips_per_device},
        )

    # ── History storage ──────────────────────────────────────────────

    async def _get_history(self, actor_key: str) -> list[dict]:
        if self._redis:
            try:
                import json
                raw = await self._redis.get(f"aether:exhist:{actor_key}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return self._actor_history.get(actor_key, [])

    async def _set_history(self, actor_key: str, history: list[dict]) -> None:
        if self._redis:
            try:
                import json
                await self._redis.setex(
                    f"aether:exhist:{actor_key}",
                    7200,  # 2 hour TTL
                    json.dumps(history),
                )
                return
            except Exception:
                pass
        self._actor_history[actor_key] = history


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _feature_hash(features: dict[str, Any]) -> str:
    """Deterministic hash of a feature dict for similarity tracking."""
    sorted_items = sorted(features.items(), key=lambda kv: kv[0])
    raw = "|".join(f"{k}={_round_val(v)}" for k, v in sorted_items)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _round_val(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _signal_weight(signal: ExtractionSignal) -> float:
    """Assign weight based on signal severity."""
    return {
        SignalSeverity.CRITICAL: 2.0,
        SignalSeverity.HIGH: 1.5,
        SignalSeverity.MEDIUM: 1.0,
        SignalSeverity.LOW: 0.5,
        SignalSeverity.INFO: 0.2,
    }.get(signal.severity, 1.0)
