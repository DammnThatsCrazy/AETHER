"""
Nightly ML drift Lambda — publishes PSI scores to CloudWatch Aether/MLDrift.

Reads 24 h of prediction scores from S3, computes PSI against a stored
reference distribution per model, and puts a single Maximum PSI metric per
model to the Aether/MLDrift CloudWatch namespace.

Expected S3 layout
------------------
Prediction logs (written by Vector/Firehose from the serving API):
  s3://<LOG_BUCKET>/predictions/<model_name>/dt=<YYYY-MM-DD>/<shard>.jsonl

Each line is a JSON object with at minimum a "score" field (float 0–1) or
a "prediction" field.  Lines that can't be parsed are skipped silently.

Reference distributions (written once after training):
  s3://<LOG_BUCKET>/drift-reference/<model_name>/reference.json
  {"scores": [0.12, 0.45, ...]}   — raw prediction scores from the training set

Environment variables
---------------------
LOG_BUCKET        S3 bucket name
MODEL_NAMES       Comma-separated list of model names
PSI_THRESHOLD     Float; logged in the metric unit but alarm threshold is in
                  the Terraform alarm resource (default 0.2)
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
cw = boto3.client("cloudwatch")

NAMESPACE = "Aether/MLDrift"
LOG_BUCKET = os.environ["LOG_BUCKET"]
MODEL_NAMES = [m.strip() for m in os.environ.get("MODEL_NAMES", "").split(",") if m.strip()]
PSI_THRESHOLD = float(os.environ.get("PSI_THRESHOLD", "0.2"))

MODELS_DEFAULT = [
    "intent_prediction",
    "bot_detection",
    "session_scorer",
    "identity_resolution",
    "journey_prediction",
    "churn_prediction",
    "ltv_prediction",
    "anomaly_detection",
    "campaign_attribution",
]


# ---------------------------------------------------------------------------
# PSI computation (no external deps — pure stdlib + math)
# ---------------------------------------------------------------------------


def _histogram(values: list[float], bin_edges: list[float]) -> list[float]:
    counts = [0.0] * (len(bin_edges) - 1)
    for v in values:
        for i in range(len(bin_edges) - 1):
            if bin_edges[i] <= v < bin_edges[i + 1]:
                counts[i] += 1.0
                break
        else:
            counts[-1] += 1.0  # right-edge inclusive
    return counts


def compute_psi(reference: list[float], current: list[float], bins: int = 10) -> float:
    if not reference or not current:
        return 0.0

    reference = sorted(reference)
    n = len(reference)
    bin_edges: list[float] = []
    for i in range(bins + 1):
        idx = min(int(i / bins * n), n - 1)
        bin_edges.append(reference[idx])

    # Deduplicate edges while preserving order
    seen: set[float] = set()
    unique_edges: list[float] = []
    for e in bin_edges:
        if e not in seen:
            seen.add(e)
            unique_edges.append(e)

    if len(unique_edges) < 3:
        lo, hi = reference[0], reference[-1]
        step = (hi - lo) / bins if hi != lo else 1.0
        unique_edges = [lo + step * i for i in range(bins + 1)]

    ref_hist = _histogram(reference, unique_edges)
    cur_hist = _histogram(current, unique_edges)

    ref_sum = sum(ref_hist) or 1.0
    cur_sum = sum(cur_hist) or 1.0

    psi = 0.0
    for r, c in zip(ref_hist, cur_hist):
        r_pct = max(r / ref_sum, 1e-6)
        c_pct = max(c / cur_sum, 1e-6)
        psi += (c_pct - r_pct) * math.log(c_pct / r_pct)

    return round(psi, 6)


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _list_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=LOG_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def _read_scores(keys: list[str]) -> list[float]:
    scores: list[float] = []
    for key in keys:
        try:
            resp = s3.get_object(Bucket=LOG_BUCKET, Key=key)
            body = resp["Body"].read()
            if key.endswith(".gz"):
                body = gzip.decompress(body)
            for line in body.decode("utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    score = obj.get("score") or obj.get("prediction")
                    if isinstance(score, (int, float)):
                        scores.append(float(score))
                    elif isinstance(score, list) and score:
                        scores.append(float(score[0]))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        except Exception as exc:
            logger.warning("Failed to read %s: %s", key, exc)
    return scores


def _read_reference(model_name: str) -> list[float]:
    key = f"drift-reference/{model_name}/reference.json"
    try:
        resp = s3.get_object(Bucket=LOG_BUCKET, Key=key)
        data = json.loads(resp["Body"].read())
        return [float(v) for v in data.get("scores", [])]
    except s3.exceptions.NoSuchKey:
        logger.info("No reference file for %s — skipping", model_name)
        return []
    except Exception as exc:
        logger.warning("Failed to read reference for %s: %s", model_name, exc)
        return []


# ---------------------------------------------------------------------------
# CloudWatch helper
# ---------------------------------------------------------------------------


def _put_psi(model_name: str, psi: float, run_date: str) -> None:
    cw.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[
            {
                "MetricName": "PSI",
                "Dimensions": [{"Name": "Model", "Value": model_name}],
                "Value": psi,
                "Unit": "None",
                "StorageResolution": 86400,
            }
        ],
    )
    logger.info("Published PSI=%.4f for model=%s date=%s", psi, model_name, run_date)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event: Any, context: Any) -> dict[str, Any]:
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    models = MODEL_NAMES or MODELS_DEFAULT

    results: dict[str, Any] = {"date": yesterday, "models": {}}

    for model_name in models:
        prefix = f"predictions/{model_name}/dt={yesterday}/"
        keys = _list_keys(prefix)

        if not keys:
            logger.info("No prediction logs for %s on %s — skipping", model_name, yesterday)
            results["models"][model_name] = {"status": "no_data"}
            continue

        current_scores = _read_scores(keys)
        if not current_scores:
            logger.info("Zero parseable scores for %s — skipping", model_name)
            results["models"][model_name] = {"status": "no_parseable_scores"}
            continue

        reference_scores = _read_reference(model_name)
        if not reference_scores:
            results["models"][model_name] = {"status": "no_reference"}
            continue

        psi = compute_psi(reference_scores, current_scores)
        _put_psi(model_name, psi, yesterday)

        results["models"][model_name] = {
            "status": "ok",
            "psi": psi,
            "drifted": psi > PSI_THRESHOLD,
            "current_samples": len(current_scores),
            "reference_samples": len(reference_scores),
        }

    drifted = [m for m, v in results["models"].items() if isinstance(v, dict) and v.get("drifted")]
    results["drifted_models"] = drifted
    results["alert"] = len(drifted) > 0

    logger.info(
        "Drift run complete: %d models, %d drifted (%s)",
        len(models),
        len(drifted),
        ", ".join(drifted) or "none",
    )
    return results
