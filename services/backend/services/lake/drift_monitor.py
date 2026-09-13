"""
ML Drift Monitor

Automated detection of feature drift and prediction drift for registered models.
Runs on schedule and reports through metrics and logging.

Integrates with existing model registry and Gold lake feature data.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from repositories.repos import BaseRepository
from services.lake.model_registry import get_active_model

logger = get_logger("aether.lake.drift_monitor")


class DriftReportRepository(BaseRepository):
    """Stores drift detection reports."""

    def __init__(self) -> None:
        super().__init__("ml_drift_reports")


drift_repo = DriftReportRepository()


async def check_feature_drift(
    model_name: str,
    reference_features: Optional[dict] = None,
    current_features: Optional[dict] = None,
) -> dict:
    """
    Compare current feature distributions against reference.
    Uses simple mean/std shift detection (PSI-like).
    """
    if not reference_features or not current_features:
        return {"model_name": model_name, "drift_detected": False, "reason": "insufficient_data"}

    drifted_features = []
    for feature_name in reference_features:
        ref_val = reference_features.get(feature_name, 0)
        cur_val = current_features.get(feature_name, 0)

        if ref_val == 0 and cur_val == 0:
            continue

        # Simple relative change detection
        if ref_val != 0:
            relative_change = abs(cur_val - ref_val) / abs(ref_val)
        else:
            relative_change = abs(cur_val)

        if relative_change > 0.3:  # 30% shift threshold
            drifted_features.append({
                "feature": feature_name,
                "reference_value": ref_val,
                "current_value": cur_val,
                "relative_change": round(relative_change, 4),
            })

    drift_detected = len(drifted_features) > 0
    if drift_detected:
        metrics.increment("ml_drift_detected", labels={"model": model_name, "type": "feature"})
        logger.warning(f"Feature drift detected for {model_name}: {len(drifted_features)} features shifted")

    return {
        "model_name": model_name,
        "drift_detected": drift_detected,
        "drifted_feature_count": len(drifted_features),
        "drifted_features": drifted_features,
        "checked_at": utc_now().isoformat(),
    }


async def check_prediction_drift(
    model_name: str,
    reference_predictions: Optional[list[float]] = None,
    current_predictions: Optional[list[float]] = None,
) -> dict:
    """
    Compare current prediction distributions against reference.
    Uses mean shift and variance change detection.
    """
    if not reference_predictions or not current_predictions:
        return {"model_name": model_name, "drift_detected": False, "reason": "insufficient_data"}

    ref_mean = sum(reference_predictions) / len(reference_predictions)
    cur_mean = sum(current_predictions) / len(current_predictions)

    ref_var = sum((x - ref_mean) ** 2 for x in reference_predictions) / len(reference_predictions)
    cur_var = sum((x - cur_mean) ** 2 for x in current_predictions) / len(current_predictions)

    mean_shift = abs(cur_mean - ref_mean)
    variance_ratio = cur_var / max(ref_var, 1e-10)

    drift_detected = mean_shift > 0.1 or variance_ratio > 2.0 or variance_ratio < 0.5

    if drift_detected:
        metrics.increment("ml_drift_detected", labels={"model": model_name, "type": "prediction"})
        logger.warning(f"Prediction drift for {model_name}: mean_shift={mean_shift:.4f}, var_ratio={variance_ratio:.4f}")

    return {
        "model_name": model_name,
        "drift_detected": drift_detected,
        "reference_mean": round(ref_mean, 4),
        "current_mean": round(cur_mean, 4),
        "mean_shift": round(mean_shift, 4),
        "variance_ratio": round(variance_ratio, 4),
        "checked_at": utc_now().isoformat(),
    }


async def run_drift_check_all() -> list[dict]:
    """Run drift checks for all registered active models."""
    results = []
    model_names = [
        "intent_prediction", "bot_detection", "session_scorer",
        "churn_prediction", "ltv_prediction", "anomaly_detection",
        "identity_resolution", "journey_prediction", "campaign_attribution",
    ]

    for model_name in model_names:
        active = await get_active_model(model_name)
        if not active:
            continue

        # Get reference features from model registration metadata
        ref_features = active.get("metrics", {}).get("reference_features", {})

        # Feature drift check
        feature_result = await check_feature_drift(model_name, ref_features)
        results.append(feature_result)

        # Store report
        import uuid
        await drift_repo.insert(str(uuid.uuid4()), {
            "model_name": model_name,
            "model_version": active.get("version", ""),
            "check_type": "feature_drift",
            "result": feature_result,
            "checked_at": utc_now().isoformat(),
        })

    metrics.increment("ml_drift_check_completed")
    logger.info(f"Drift check complete: {len(results)} models checked")
    return results


async def drift_monitor_loop(interval_seconds: int = 3600) -> None:
    """Run drift monitoring on a schedule."""
    logger.info(f"ML drift monitor started: interval={interval_seconds}s")
    while True:
        try:
            await run_drift_check_all()
        except Exception as e:
            logger.error(f"Drift monitor failed: {e}")
            metrics.increment("ml_drift_check_failed")
        await asyncio.sleep(interval_seconds)
