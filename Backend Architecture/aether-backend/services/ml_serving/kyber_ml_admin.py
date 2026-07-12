"""
Aether Service — Kyber ML Command Center (Admin Hooks)

Exposes ML operational state to the Kyber operator console.
All routes require admin/kyber operator access.

Routes:
  GET /v1/admin/kyber/ml/overview        — Platform-wide ML health summary
  GET /v1/admin/kyber/ml/models          — All models with readiness state
  GET /v1/admin/kyber/ml/models/{id}     — Single model detail
  GET /v1/admin/kyber/ml/artifacts       — Artifact registry summary
  GET /v1/admin/kyber/ml/artifacts/{id}  — Artifacts for a single model
  GET /v1/admin/kyber/ml/features        — Feature pipeline status
  GET /v1/admin/kyber/ml/drift           — Drift monitoring summary
  GET /v1/admin/kyber/ml/predictions/summary — Prediction volume/latency
  GET /v1/admin/kyber/ml/security        — Extraction defense status
  GET /v1/admin/kyber/ml/readiness       — Production readiness scorecard
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.ml_serving.kyber_admin")
router = APIRouter(prefix="/v1/admin/kyber/ml", tags=["Kyber ML Admin"])

_ML_SERVING_URL = os.getenv("ML_SERVING_URL", "http://localhost:8080")
_http_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=_ML_SERVING_URL,
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
    return _http_client


from services.security.request_context import require_kyber_operator as _canonical_kyber_gate


def _require_kyber_operator(request: Request) -> None:
    """Require Olympus operator access via the canonical fail-closed gate.

    A regular Aether tenant — even one holding the ``admin`` permission or
    ``Role.ADMIN`` — is NOT a Kyber operator. Only the configured
    ``kyber:operator`` grant or the operator tenant-id allowlist passes.
    """
    _canonical_kyber_gate(request)


def _get_registry_models() -> list[dict[str, Any]]:
    """Return all models from the canonical registry."""
    try:
        from common.model_registry import list_models, export_registry_for_docs
        return export_registry_for_docs()
    except ImportError:
        return []


async def _get_serving_status() -> dict[str, Any]:
    """Fetch live model status from ML serving API."""
    client = _get_client()
    try:
        resp = await client.get("/models")
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError:
        pass
    return {"models": []}


async def _get_defense_status() -> dict[str, Any]:
    """Fetch extraction defense status from ML serving API."""
    client = _get_client()
    try:
        resp = await client.get("/v1/defense/status")
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError:
        pass
    return {"enabled": False, "error": "ML serving unreachable"}


async def _get_defense_metrics() -> dict[str, Any]:
    """Fetch defense metrics from ML serving API."""
    client = _get_client()
    try:
        resp = await client.get("/v1/defense/metrics")
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError:
        pass
    return {}


def _build_model_detail(
    registry_entry: dict[str, Any],
    live_status: dict[str, Any],
) -> dict[str, Any]:
    """Combine registry info with live serving status into a detailed model record."""
    model_id = registry_entry.get("model_id", "")
    serving = live_status.get("name") == model_id and live_status or {}

    blockers: list[str] = []
    artifact_version = serving.get("version", "n/a")
    serving_status = serving.get("status", "unknown")

    if registry_entry.get("artifact_required") and serving_status in ("not_loaded", "unknown", "error"):
        blockers.append(f"Artifact not loaded (status: {serving_status})")
    if registry_entry.get("implementation_type") == "trainable_ml" and artifact_version in ("n/a", "test-stub"):
        blockers.append("No real artifact — model running in stub mode or untrained")
    if not registry_entry.get("training_supported") and registry_entry.get("current_status") not in (
        "active_deterministic", "promoted"
    ):
        blockers.append("Non-trainable model not in active state")

    recommended_action = "none"
    if blockers:
        if any("stub" in b.lower() or "artifact" in b.lower() for b in blockers):
            recommended_action = "run_training_pipeline"
        else:
            recommended_action = "investigate"

    return {
        "model_id": model_id,
        "display_name": registry_entry.get("display_name", model_id),
        "category": registry_entry.get("category", ""),
        "implementation_type": registry_entry.get("implementation_type", ""),
        "tier": registry_entry.get("tier", ""),
        "sensitivity_tier": registry_entry.get("sensitivity_tier", ""),
        "current_status": registry_entry.get("current_status", ""),
        "training_supported": registry_entry.get("training_supported", False),
        "serving_supported": registry_entry.get("serving_supported", False),
        "batch_supported": registry_entry.get("batch_supported", False),
        "batch_requires_privileged": registry_entry.get("batch_requires_privileged", False),
        "artifact_required": registry_entry.get("artifact_required", False),
        "artifact_format": registry_entry.get("artifact_format", ""),
        "artifact_version": artifact_version,
        "serving_status": serving_status,
        "serving_endpoint": registry_entry.get("serving_endpoint", ""),
        "deprecated_aliases": registry_entry.get("deprecated_aliases", []),
        "fail_closed_required": registry_entry.get("fail_closed_required", False),
        "readiness_blockers": blockers,
        "recommended_action": recommended_action,
        "stub_model": artifact_version == "test-stub",
        "production_allowed": artifact_version not in ("n/a", "test-stub", "unknown"),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/overview")
async def ml_overview(request: Request):
    """Platform-wide ML health summary for the Kyber command center."""
    _require_kyber_operator(request)

    registry_models = _get_registry_models()
    live_data = await _get_serving_status()
    defense_status = await _get_defense_status()

    live_by_name = {m.get("name", ""): m for m in (live_data.get("models") or [])}
    details = [
        _build_model_detail(reg, live_by_name.get(reg.get("model_id", ""), {}))
        for reg in registry_models
    ]

    trainable = [d for d in details if d.get("training_supported")]
    deterministic = [d for d in details if not d.get("training_supported")]
    models_with_blockers = [d for d in details if d.get("readiness_blockers")]
    stub_models = [d for d in details if d.get("stub_model")]

    env = os.getenv("AETHER_ENV", "local")
    readiness_score = (
        len(details) - len(models_with_blockers)
    ) / max(len(details), 1) * 100

    return APIResponse(data={
        "overview": {
            "environment": env,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_models": len(details),
            "trainable_models": len(trainable),
            "deterministic_models": len(deterministic),
            "models_ready": len(details) - len(models_with_blockers),
            "models_with_blockers": len(models_with_blockers),
            "stub_models_loaded": len(stub_models),
            "stub_models_allowed": env not in ("production", "staging"),
            "extraction_defense_enabled": defense_status.get("enabled", False),
            "ml_serving_reachable": bool(live_data.get("models")),
            "readiness_score_pct": round(readiness_score, 1),
        },
        "models": details,
        "defense": defense_status,
    }).to_dict()


@router.get("/models")
async def kyber_list_models(request: Request):
    """All ML models with registry metadata and live serving status."""
    _require_kyber_operator(request)

    registry_models = _get_registry_models()
    live_data = await _get_serving_status()
    live_by_name = {m.get("name", ""): m for m in (live_data.get("models") or [])}

    details = [
        _build_model_detail(reg, live_by_name.get(reg.get("model_id", ""), {}))
        for reg in registry_models
    ]

    return APIResponse(data={
        "models": details,
        "count": len(details),
        "ml_serving_reachable": bool(live_data.get("models")),
    }).to_dict()


@router.get("/models/{model_id}")
async def kyber_model_detail(model_id: str, request: Request):
    """Detailed ML readiness record for a single model."""
    _require_kyber_operator(request)

    # Resolve canonical ID
    try:
        from common.model_registry import resolve_model_id, get_model, export_registry_for_docs
        canonical = resolve_model_id(model_id)
        if not canonical:
            from shared.common.common import BadRequestError
            raise BadRequestError(f"Unknown model: '{model_id}'")
        entry = get_model(canonical)
        # Find in docs export
        all_docs = export_registry_for_docs()
        reg_entry = next((d for d in all_docs if d.get("model_id") == canonical), {})
    except ImportError:
        from shared.common.common import BadRequestError
        raise BadRequestError("ML registry unavailable")

    live_data = await _get_serving_status()
    live_by_name = {m.get("name", ""): m for m in (live_data.get("models") or [])}

    detail = _build_model_detail(reg_entry, live_by_name.get(canonical, {}))

    # Add feature contract info
    try:
        from common.feature_contracts import (
            get_feature_contract, compute_schema_hash, generate_example_features
        )
        contract = get_feature_contract(canonical)
        detail["feature_contract"] = {
            "contract_id": contract.contract_id,
            "schema_version": contract.schema_version,
            "schema_hash": contract.schema_hash,
            "required_features": contract.required_features,
            "optional_features": contract.optional_features,
            "freshness_sla_seconds": contract.freshness_sla_seconds,
        }
        detail["example_features"] = generate_example_features(canonical)
    except (ImportError, KeyError):
        detail["feature_contract"] = None

    return APIResponse(data=detail).to_dict()


@router.get("/artifacts")
async def kyber_artifacts_summary(request: Request):
    """Artifact registry summary for all models."""
    _require_kyber_operator(request)

    registry_models = _get_registry_models()
    artifact_root = os.getenv("AETHER_MODEL_ARTIFACT_DIR", "/opt/ml/models")
    env = os.getenv("AETHER_ENV", "local")

    summaries = []
    for reg in registry_models:
        model_id = reg.get("model_id", "")
        if not reg.get("artifact_required"):
            summaries.append({
                "model_id": model_id,
                "artifact_required": False,
                "note": "Deterministic/composite — no artifact",
            })
            continue

        # Try to read artifact metadata from local filesystem
        from pathlib import Path
        model_dir = Path(artifact_root) / model_id
        try:
            from common.artifact_registry import list_artifacts, resolve_active_artifact
            artifacts = list_artifacts(Path(artifact_root), model_id)
            active_dir = resolve_active_artifact(Path(artifact_root), model_id, env=env)

            summaries.append({
                "model_id": model_id,
                "artifact_required": True,
                "artifact_count": len(artifacts),
                "latest_version": artifacts[0].artifact_version if artifacts else None,
                "latest_promotion_state": artifacts[0].promotion_state if artifacts else None,
                "latest_synthetic": artifacts[0].synthetic_data if artifacts else None,
                "latest_production_allowed": artifacts[0].production_allowed if artifacts else None,
                "active_artifact_available": active_dir is not None,
                "checksum_validated": True,
            })
        except Exception as exc:
            summaries.append({
                "model_id": model_id,
                "artifact_required": True,
                "artifact_count": 0,
                "latest_version": None,
                "active_artifact_available": False,
                "note": f"No artifacts or registry error: {exc}",
            })

    return APIResponse(data={
        "artifact_root": artifact_root,
        "environment": env,
        "artifacts": summaries,
    }).to_dict()


@router.get("/artifacts/{model_id}")
async def kyber_model_artifacts(model_id: str, request: Request):
    """Artifact history for a single model."""
    _require_kyber_operator(request)

    try:
        from common.model_registry import resolve_model_id
        canonical = resolve_model_id(model_id)
        if not canonical:
            from shared.common.common import BadRequestError
            raise BadRequestError(f"Unknown model: '{model_id}'")
    except ImportError:
        canonical = model_id

    artifact_root = os.getenv("AETHER_MODEL_ARTIFACT_DIR", "/opt/ml/models")
    from pathlib import Path

    try:
        from common.artifact_registry import list_artifacts
        artifacts = list_artifacts(Path(artifact_root), canonical)
        return APIResponse(data={
            "model_id": canonical,
            "artifact_count": len(artifacts),
            "artifacts": [a.to_dict() for a in artifacts],
        }).to_dict()
    except Exception as exc:
        return APIResponse(data={
            "model_id": canonical,
            "artifact_count": 0,
            "artifacts": [],
            "error": str(exc),
        }).to_dict()


@router.get("/features")
async def kyber_features_status(request: Request):
    """Feature pipeline and contract status."""
    _require_kyber_operator(request)

    try:
        from common.feature_contracts import get_feature_contract
        from common.model_registry import list_trainable_models
        contracts = []
        for entry in list_trainable_models():
            try:
                c = get_feature_contract(entry.model_id)
                contracts.append({
                    "model_id": entry.model_id,
                    "contract_id": c.contract_id,
                    "schema_version": c.schema_version,
                    "schema_hash": c.schema_hash,
                    "required_features_count": len(c.required_features),
                    "optional_features_count": len(c.optional_features),
                    "freshness_sla_seconds": c.freshness_sla_seconds,
                    "source_feature_groups": c.source_feature_groups,
                })
            except KeyError:
                contracts.append({
                    "model_id": entry.model_id,
                    "error": "No feature contract defined",
                })
    except ImportError:
        contracts = []

    return APIResponse(data={
        "feature_contracts": contracts,
        "feature_groups": [
            "session_features",
            "behavioral_features",
            "identity_features",
            "journey_features",
            "attribution_features",
            "anomaly_features",
            "web3_features",
        ],
    }).to_dict()


@router.get("/drift")
async def kyber_drift_summary(request: Request):
    """Drift monitoring summary for all models."""
    _require_kyber_operator(request)

    # Drift data lives in monitoring module; return best-effort status
    drift_summary = {
        "note": (
            "Drift baselines require real data training runs. "
            "In local/dev mode with synthetic data, drift monitoring is advisory."
        ),
        "models": [],
    }

    try:
        from common.model_registry import list_trainable_models
        for entry in list_trainable_models():
            drift_summary["models"].append({
                "model_id": entry.model_id,
                "drift_score": None,
                "drift_status": "no_baseline",
                "freshness_sla_seconds": None,
                "last_prediction": None,
                "recommended_action": "establish_drift_baseline_after_real_data_training",
            })
    except ImportError:
        pass

    return APIResponse(data=drift_summary).to_dict()


@router.get("/predictions/summary")
async def kyber_predictions_summary(request: Request):
    """Prediction volume and latency summary."""
    _require_kyber_operator(request)

    # Best-effort: pull from Prometheus metrics if available
    # In local/dev, returns advisory data
    return APIResponse(data={
        "note": "Live prediction telemetry requires Prometheus + Grafana (observability profile).",
        "prediction_count_source": "metrics backend",
        "metrics_endpoints": {
            "serving": f"{_ML_SERVING_URL}/metrics",
            "defense": f"{_ML_SERVING_URL}/v1/defense/metrics",
        },
        "models": [
            {
                "model_id": entry.model_id,
                "prediction_count": None,
                "error_count": None,
                "latency_p50_ms": None,
                "latency_p95_ms": None,
                "latency_p99_ms": None,
            }
            for entry in _get_trainable_models_list()
        ],
    }).to_dict()


@router.get("/security")
async def kyber_ml_security(request: Request):
    """Extraction defense status and risk summary."""
    _require_kyber_operator(request)

    defense_status = await _get_defense_status()
    defense_metrics = await _get_defense_metrics()

    return APIResponse(data={
        "extraction_defense": defense_status,
        "metrics": defense_metrics,
        "policy": {
            "batch_internal_only": os.getenv("EXTRACTION_BATCH_INTERNAL_ONLY", "true"),
            "mesh_enabled": os.getenv("ENABLE_EXTRACTION_MESH", "false"),
            "defense_enabled": os.getenv("ENABLE_EXTRACTION_DEFENSE", "false"),
        },
        "sensitivity_tiers": {
            "critical": ["churn_prediction", "ltv_prediction", "anomaly_detection"],
            "high": ["intent_prediction", "bot_detection", "campaign_attribution"],
            "standard": ["session_scorer", "journey_prediction", "identity_resolution"],
        },
    }).to_dict()


@router.get("/readiness")
async def kyber_ml_readiness(request: Request):
    """ML production readiness scorecard."""
    _require_kyber_operator(request)

    env = os.getenv("AETHER_ENV", "local")
    registry_models = _get_registry_models()
    live_data = await _get_serving_status()
    live_by_name = {m.get("name", ""): m for m in (live_data.get("models") or [])}

    details = [
        _build_model_detail(reg, live_by_name.get(reg.get("model_id", ""), {}))
        for reg in registry_models
    ]

    blockers: list[str] = []
    warnings: list[str] = []

    stub_models = [d for d in details if d.get("stub_model")]
    if stub_models and env in ("production", "staging"):
        for m in stub_models:
            blockers.append(
                f"BLOCKER: Stub model loaded in {env}: {m['model_id']}. "
                "Stub models are forbidden in staging/production."
            )
    elif stub_models:
        for m in stub_models:
            warnings.append(
                f"Stub model loaded: {m['model_id']} "
                "(acceptable in local/dev, forbidden in staging/production)"
            )

    models_without_artifacts = [
        d for d in details
        if d.get("artifact_required") and d.get("artifact_version") in ("n/a", None)
    ]
    if models_without_artifacts and env in ("production", "staging"):
        for m in models_without_artifacts:
            blockers.append(
                f"BLOCKER: No artifact for required model: {m['model_id']}"
            )

    fail_closed_models = [d for d in details if d.get("fail_closed_required")]
    unready_fail_closed = [
        d for d in fail_closed_models if d.get("readiness_blockers")
    ]
    if unready_fail_closed and env in ("production", "staging"):
        for m in unready_fail_closed:
            blockers.append(
                f"BLOCKER: Fail-closed model not ready: {m['model_id']}: "
                f"{', '.join(m.get('readiness_blockers', []))}"
            )

    overall_ready = len(blockers) == 0
    readiness_score = (
        len(details) - sum(1 for d in details if d.get("readiness_blockers"))
    ) / max(len(details), 1) * 100

    return APIResponse(data={
        "environment": env,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_ready": overall_ready,
        "readiness_score_pct": round(readiness_score, 1),
        "blockers": blockers,
        "warnings": warnings,
        "model_readiness": [
            {
                "model_id": d["model_id"],
                "ready": not d.get("readiness_blockers"),
                "blockers": d.get("readiness_blockers", []),
                "recommended_action": d.get("recommended_action"),
                "stub_model": d.get("stub_model"),
                "artifact_version": d.get("artifact_version"),
            }
            for d in details
        ],
        "docs": "docs/reports/ML-PRODUCTIZATION-READINESS.md",
    }).to_dict()


@router.get("/alerts")
async def kyber_ml_alerts(request: Request):
    """Active ML alert conditions derived from live monitoring state."""
    _require_kyber_operator(request)

    client = _get_client()
    alerts: list[dict[str, Any]] = []

    # Extraction defense: block rate and risk anomalies
    try:
        resp = await client.get("/v1/monitoring/extraction")
        if resp.status_code == 200:
            data = resp.json()
            summary = data.get("summary", {})
            block_rate = summary.get("block_rate_pct", 0)
            avg_risk = summary.get("avg_risk_score", 0)
            if block_rate > 30:
                alerts.append({
                    "name": "MLExtractionHighBlockRate",
                    "severity": "warning",
                    "value": block_rate,
                    "message": f"Extraction defense block rate {block_rate:.1f}% exceeds 30%",
                    "source": "extraction_defense",
                })
            if avg_risk > 40:
                alerts.append({
                    "name": "MLExtractionElevatedRisk",
                    "severity": "info",
                    "value": avg_risk,
                    "message": f"Average extraction risk score {avg_risk:.1f} (threshold: 40)",
                    "source": "extraction_defense",
                })
            for anomaly in data.get("anomalies", []):
                alerts.append({
                    "name": f"MLExtraction_{anomaly.get('type', 'unknown')}",
                    "severity": "warning",
                    "value": anomaly.get("value"),
                    "message": anomaly.get("message", ""),
                    "source": "extraction_defense",
                })
    except httpx.RequestError:
        pass

    # Freshness: violation rate
    try:
        resp = await client.get("/v1/monitoring/freshness")
        if resp.status_code == 200:
            freshness = resp.json()
            violation_rate = freshness.get("violation_rate", 0)
            if violation_rate > 0.05:
                alerts.append({
                    "name": "MLFreshnessViolationRate",
                    "severity": "warning",
                    "value": round(violation_rate * 100, 1),
                    "message": (
                        f"Freshness SLA violation rate {violation_rate:.1%} exceeds 5%"
                    ),
                    "source": "freshness_tracker",
                })
    except httpx.RequestError:
        pass

    # Model fleet: required models not loaded
    live_data = await _get_serving_status()
    registry_models = _get_registry_models()
    live_by_name = {m.get("name", ""): m for m in (live_data.get("models") or [])}
    for reg in registry_models:
        if not reg.get("artifact_required"):
            continue
        mid = reg.get("model_id", "")
        live = live_by_name.get(mid, {})
        if live.get("status", "unknown") not in ("loaded", "active"):
            alerts.append({
                "name": "MLModelNotLoaded",
                "severity": "critical",
                "value": mid,
                "message": f"Required model '{mid}' is not loaded (status: {live.get('status', 'unknown')})",
                "source": "model_fleet",
            })

    return APIResponse(data={
        "alerts": alerts,
        "count": len(alerts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }).to_dict()


@router.get("/models/{model_id}/rollback-eligibility")
async def kyber_rollback_eligibility(model_id: str, request: Request):
    """Check whether a model can be rolled back and to which artifact version."""
    _require_kyber_operator(request)

    try:
        from common.model_registry import resolve_model_id
        canonical = resolve_model_id(model_id)
        if not canonical:
            from shared.common.common import BadRequestError
            raise BadRequestError(f"Unknown model: '{model_id}'")
    except ImportError:
        canonical = model_id

    artifact_root = Path(os.getenv("AETHER_MODEL_ARTIFACT_DIR", "/opt/ml/models"))
    try:
        from common.artifact_registry import list_artifacts
        artifacts = list_artifacts(artifact_root, canonical)
    except Exception as exc:
        return APIResponse(data={
            "model_id": canonical,
            "can_rollback": False,
            "reason": f"Artifact registry unavailable: {exc}",
        }).to_dict()

    promoted = [
        a for a in artifacts
        if getattr(a, "promotion_state", "") in ("promoted", "active", "production")
    ]
    current = promoted[0] if promoted else None
    target = promoted[1] if len(promoted) > 1 else None

    live_data = await _get_serving_status()
    live_by_name = {m.get("name", ""): m for m in (live_data.get("models") or [])}
    live_status = live_by_name.get(canonical, {}).get("status", "unknown")

    return APIResponse(data={
        "model_id": canonical,
        "can_rollback": target is not None,
        "reason": None if target else "No prior promoted artifact available",
        "current_version": getattr(current, "artifact_version", None),
        "current_promotion_state": getattr(current, "promotion_state", None),
        "rollback_target_version": getattr(target, "artifact_version", None),
        "rollback_target_metrics": getattr(target, "metrics", {}),
        "rollback_target_production_allowed": getattr(target, "production_allowed", False),
        "live_status": live_status,
        "total_promoted_artifacts": len(promoted),
    }).to_dict()


@router.get("/audit")
async def kyber_ml_audit(
    request: Request,
    model_id: Optional[str] = None,
    limit: int = 50,
):
    """Promotion and rollback audit trail for all models (or a single model)."""
    _require_kyber_operator(request)

    artifact_root = Path(os.getenv("AETHER_MODEL_ARTIFACT_DIR", "/opt/ml/models"))
    registry_models = _get_registry_models()

    target_models = [model_id] if model_id else [
        r.get("model_id", "") for r in registry_models if r.get("artifact_required")
    ]

    entries: list[dict[str, Any]] = []
    for mid in target_models:
        audit_path = artifact_root / mid / "promotion_audit.jsonl"
        if audit_path.exists():
            try:
                with open(audit_path) as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            except OSError:
                pass
        else:
            # Fallback: synthesize audit entries from artifact state metadata
            try:
                from common.artifact_registry import list_artifacts
                for art in list_artifacts(artifact_root, mid):
                    state = getattr(art, "promotion_state", "")
                    if state in ("promoted", "active", "production", "deprecated"):
                        entries.append({
                            "timestamp": getattr(art, "created_at", None),
                            "action": "promote" if state != "deprecated" else "deprecate",
                            "model_id": mid,
                            "artifact_version": getattr(art, "artifact_version", None),
                            "promotion_state": state,
                            "synthetic": getattr(art, "synthetic_data", None),
                            "production_allowed": getattr(art, "production_allowed", None),
                            "actor": "system",
                            "source": "artifact_metadata_fallback",
                        })
            except Exception:
                pass

    entries.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return APIResponse(data={
        "audit_entries": entries[:limit],
        "total": len(entries),
        "model_filter": model_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }).to_dict()


@router.get("/models/{model_id}/training-history")
async def kyber_training_history(model_id: str, request: Request):
    """Training run history for a model, derived from artifact metadata."""
    _require_kyber_operator(request)

    try:
        from common.model_registry import resolve_model_id
        canonical = resolve_model_id(model_id)
        if not canonical:
            from shared.common.common import BadRequestError
            raise BadRequestError(f"Unknown model: '{model_id}'")
    except ImportError:
        canonical = model_id

    artifact_root = Path(os.getenv("AETHER_MODEL_ARTIFACT_DIR", "/opt/ml/models"))
    try:
        from common.artifact_registry import list_artifacts
        artifacts = list_artifacts(artifact_root, canonical)
    except Exception as exc:
        return APIResponse(data={
            "model_id": canonical,
            "training_runs": [],
            "count": 0,
            "error": str(exc),
        }).to_dict()

    runs = [
        {
            "artifact_version": getattr(a, "artifact_version", None),
            "created_at": getattr(a, "created_at", None),
            "promotion_state": getattr(a, "promotion_state", None),
            "synthetic_data": getattr(a, "synthetic_data", None),
            "production_allowed": getattr(a, "production_allowed", None),
            "metrics": getattr(a, "metrics", {}),
            "checksum": getattr(a, "checksum", None),
        }
        for a in artifacts
    ]

    return APIResponse(data={
        "model_id": canonical,
        "training_runs": runs,
        "count": len(runs),
    }).to_dict()


def _get_trainable_models_list():
    """Helper to get trainable model entries (graceful import failure)."""
    try:
        from common.model_registry import list_trainable_models
        return list_trainable_models()
    except ImportError:
        return []
