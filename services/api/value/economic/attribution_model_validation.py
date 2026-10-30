"""Append-only validation evidence for exact attribution model configuration lineage.

This checks a completed run's recorded config snapshot against the tenant's
current attribution model config. It does not evaluate model
performance, approve a model, or calibrate its reported confidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID


_local_decisions: dict[tuple[str, str], dict[str, Any]] = {}


def _uuid(value: Any) -> Optional[str]:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _snapshot(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) and value else None


_EFFECTIVE_OVERRIDE_FIELDS = {
    "click_lookback_window", "view_lookback_window",
    "identity_confidence_min", "fraud_policy", "direct_traffic_policy",
    "engaged_view_threshold_ms",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def _decision_for(
    tenant_id: str, run: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    run_id = _uuid(run.get("attribution_run_id"))
    config_id = _uuid(run.get("model_config_id"))
    snap = _snapshot(run.get("model_config_snapshot"))
    run_created = _utc(run.get("created_at"))
    config_effective = _utc(config.get("effective_from"))
    config_until = _utc(config.get("effective_until"))
    model_type = run.get("model_type")
    model_version = run.get("model_version")
    if (
        not tenant_id
        or run.get("tenant_id") != tenant_id
        or run.get("status") != "complete"
        or run_id is None
        or config_id is None
        or snap is None
        or not _EFFECTIVE_OVERRIDE_FIELDS.issubset(snap)
        or config.get("tenant_id") != tenant_id
        or _uuid(config.get("model_config_id")) != config_id
        or _uuid(snap.get("model_config_id")) != config_id
        or not isinstance(model_type, str)
        or not model_type
        or not isinstance(model_version, str)
        or not model_version
        or config.get("model_type") != model_type
        or config.get("model_version") != model_version
        or config.get("status") not in {"active", "archived", "inactive"}
        or snap.get("model_type") != model_type
        or snap.get("model_version") != model_version
        or run_created is None
        or config_effective is None
        or config_effective > run_created
        or (config.get("effective_until") is not None and config_until is None)
        or (config_until is not None and config_until <= run_created)
        or any(
            key not in snap or _canonical(snap[key]) != _canonical(value)
            for key, value in config.items()
            if key not in _EFFECTIVE_OVERRIDE_FIELDS
        )
    ):
        raise ValueError("attribution model configuration lineage is not exact and complete")
    snapshot_json = _canonical(snap)
    snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
    decision_id = "amv_" + hashlib.sha256(
        f"{tenant_id}:{run_id}:{config_id}:{snapshot_hash}".encode("utf-8")
    ).hexdigest()[:32]
    return {
        "decision_id": decision_id,
        "tenant_id": tenant_id,
        "attribution_run_id": run_id,
        "model_config_id": config_id,
        "model_type": model_type,
        "model_version": model_version,
        "config_snapshot_sha256": snapshot_hash,
        "validation_state": "exact_config_lineage_validated",
        "calibration_state": "unvalidated",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class AttributionModelValidationRepository:
    """Append-only tenant/run decision store; one validated lineage per run."""

    async def get(self, tenant_id: str, run_id: str) -> Optional[dict[str, Any]]:
        canonical_run_id = _uuid(run_id)
        if not tenant_id or canonical_run_id is None:
            return None
        from repositories.repos import get_pool

        pool = await get_pool()
        if pool is None:
            if os.environ.get("AETHER_ENV", "local").lower() not in {"local", "dev", "test"}:
                raise RuntimeError("attribution model validation requires PostgreSQL")
            row = _local_decisions.get((tenant_id, canonical_run_id))
            return dict(row) if row is not None else None
        row = await pool.fetchrow(
            "SELECT * FROM attribution_model_validation_decisions "
            "WHERE tenant_id=$1 AND attribution_run_id=$2",
            tenant_id, UUID(canonical_run_id),
        )
        return dict(row) if row is not None else None

    async def insert(self, decision: dict[str, Any]) -> dict[str, Any]:
        tenant_id = decision["tenant_id"]
        run_id = decision["attribution_run_id"]
        existing = await self.get(tenant_id, run_id)
        if existing is not None:
            if not _same_decision(existing, decision):
                raise ValueError("attribution run has a conflicting model validation decision")
            return existing
        from repositories.repos import get_pool

        pool = await get_pool()
        if pool is None:
            if os.environ.get("AETHER_ENV", "local").lower() not in {"local", "dev", "test"}:
                raise RuntimeError("attribution model validation requires PostgreSQL")
            _local_decisions[(tenant_id, run_id)] = dict(decision)
            return dict(decision)
        await pool.execute(
            "INSERT INTO attribution_model_validation_decisions "
            "(decision_id, tenant_id, attribution_run_id, model_config_id, "
            "model_type, model_version, config_snapshot_sha256, validation_state, "
            "calibration_state, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT DO NOTHING",
            decision["decision_id"], tenant_id, UUID(run_id),
            UUID(decision["model_config_id"]), decision["model_type"],
            decision["model_version"], decision["config_snapshot_sha256"],
            decision["validation_state"], decision["calibration_state"],
            _utc(decision["created_at"]),
        )
        stored = await self.get(tenant_id, run_id)
        if stored is None:
            raise RuntimeError("attribution model validation insert was not persisted")
        if not _same_decision(stored, decision):
            raise ValueError("attribution run has a conflicting model validation decision")
        return stored


def _same_decision(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _uuid(left.get("model_config_id")) != _uuid(right.get("model_config_id")):
        return False
    if _uuid(left.get("attribution_run_id")) != _uuid(right.get("attribution_run_id")):
        return False
    return all(left.get(key) == right.get(key) for key in (
        "decision_id", "tenant_id", "model_type",
        "model_version", "config_snapshot_sha256", "validation_state",
        "calibration_state",
    ))


async def validate_attribution_run_model(
    tenant_id: str,
    run_id: str,
    *,
    runs: Any = None,
    decisions: Optional[AttributionModelValidationRepository] = None,
) -> dict[str, Any]:
    """Persist exact model-lineage validation for one completed tenant run."""
    canonical_run_id = _uuid(run_id)
    if not tenant_id or canonical_run_id is None:
        raise ValueError("exact tenant and attribution run ID are required")
    if runs is None:
        from journeys.measurement.repositories.attribution_run_repo import AttributionRunRepository

        runs = AttributionRunRepository()
    run = await runs.get_run(canonical_run_id, tenant_id=tenant_id)
    if (
        not isinstance(run, dict)
        or run.get("tenant_id") != tenant_id
        or _uuid(run.get("attribution_run_id")) != canonical_run_id
    ):
        raise ValueError("tenant attribution run is unavailable")
    config_id = _uuid(run.get("model_config_id"))
    if config_id is None:
        raise ValueError("attribution run has no exact model config ID")
    config = await runs.get_model_config(tenant_id, config_id)
    if not isinstance(config, dict):
        raise ValueError("tenant attribution model config is unavailable")
    decision = _decision_for(tenant_id, run, config)
    return await (decisions or AttributionModelValidationRepository()).insert(decision)


__all__ = [
    "AttributionModelValidationRepository",
    "validate_attribution_run_model",
]
