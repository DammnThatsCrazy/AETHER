"""Score traffic windows with the ML ``anomaly_detection`` model.

Uses the same ML serving client as ``/v1/ml/predict`` (``ML_SERVING_URL``,
inline router in consolidated profiles) and its ``/v1/predict/batch``
endpoint with ``model=anomaly_detection``. The model's feature contract
requires the ``analytics`` and ``fraud_prevention`` purposes; window rows are
tenant aggregates (no subject identifiers), so no per-subject consent applies,
and the request is tagged with both purposes.

Failures (serving down, model not trained, contract rejection) are returned
as an explicit status and never fail the discovery run.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from .detectors.ml_windows import MODEL, window_features

logger = get_logger("aether.pattern_discovery.ml")
TIMEOUT_SECONDS = 10.0


async def score_windows(extraction, client: Optional[Any] = None) -> tuple[dict[str, float], dict[str, Any]]:
    """``({window_start: score}, report)`` for the extraction's hourly windows."""
    windows = window_features([e for e in extraction.events if e.entity or e.ts])
    if not windows:
        return {}, {"status": "no_windows"}
    if client is None:
        from intelligence.ml_serving.routes import _get_client

        client = _get_client()
    payload = {"model": MODEL, "instances": [w["features"] for w in windows],
               "purposes": ["analytics", "fraud_prevention"]}
    try:
        resp = await client.post("/v1/predict/batch", json=payload, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - ML is an enrichment, not a dependency
        logger.warning("pattern_discovery.ml_unreachable", extra={"error_type": type(exc).__name__})
        return {}, {"status": "unreachable", "error_type": type(exc).__name__, "windows": len(windows)}
    if resp.status_code != 200:
        return {}, {"status": f"http_{resp.status_code}", "windows": len(windows)}
    try:
        body = resp.json()
        preds = body.get("predictions", [])
    except Exception:  # noqa: BLE001
        return {}, {"status": "bad_response", "windows": len(windows)}
    if len(preds) != len(windows):
        return {}, {"status": "prediction_count_mismatch", "windows": len(windows), "predictions": len(preds)}
    scores: dict[str, float] = {}
    for w, p in zip(windows, preds):
        value = p.get("anomaly_score", p.get("score", p.get("prediction"))) if isinstance(p, dict) else p
        try:
            scores[w["window_start"]] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return scores, {"status": "scored", "windows": len(windows), "scored": len(scores),
                    "flagged": sum(1 for s in scores.values() if s > 0.5)}
