"""
Aether — Model Artifact Registry

Manages ML model lifecycle:
- Register trained model artifacts with metadata
- Version management (active, candidate, previous)
- Rollback to previous versions
- Health and drift monitoring hooks
"""

from __future__ import annotations

from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.lake.model_registry")


class ModelRegistryRepository(BaseRepository):
    """Stores model version metadata. Actual artifacts go to S3."""

    def __init__(self) -> None:
        super().__init__("model_registry")


_registry = ModelRegistryRepository()


async def register_model(
    model_name: str,
    version: str,
    artifact_path: str,
    metrics_snapshot: dict,
    dataset_version: str = "",
    feature_version: str = "",
    training_config: Optional[dict] = None,
) -> dict:
    """Register a trained model artifact."""
    record_id = f"{model_name}:{version}"
    data = {
        "model_name": model_name,
        "version": version,
        "artifact_path": artifact_path,
        "status": "candidate",  # candidate → active → retired
        "metrics": metrics_snapshot,
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "training_config": training_config or {},
        "registered_at": utc_now().isoformat(),
    }
    result = await _registry.insert(record_id, data)
    logger.info(f"Model registered: {model_name} v{version} at {artifact_path}")
    metrics.increment("model_registered", labels={"model": model_name})
    return result


async def promote_model(model_name: str, version: str) -> dict:
    """Promote a candidate model to active. Retires previous active version."""
    record_id = f"{model_name}:{version}"
    candidate = await _registry.find_by_id(record_id)
    if not candidate:
        raise NotFoundError(f"Model {model_name} v{version}")

    # Retire current active
    active_versions = await _registry.find_many(
        filters={"model_name": model_name, "status": "active"}, limit=10
    )
    for av in active_versions:
        await _registry.update(av["id"], {"status": "retired"})

    # Promote candidate
    result = await _registry.update(record_id, {"status": "active", "promoted_at": utc_now().isoformat()})
    logger.info(f"Model promoted: {model_name} v{version}")
    metrics.increment("model_promoted", labels={"model": model_name})
    return result


async def rollback_model(model_name: str) -> dict:
    """Rollback to the most recent retired version."""
    retired = await _registry.find_many(
        filters={"model_name": model_name, "status": "retired"},
        limit=1,
        sort_by="updated_at",
        sort_order="desc",
    )
    if not retired:
        raise NotFoundError(f"No retired version of {model_name} to rollback to")

    previous = retired[0]

    # Retire current active
    active = await _registry.find_many(
        filters={"model_name": model_name, "status": "active"}, limit=1
    )
    for av in active:
        await _registry.update(av["id"], {"status": "retired"})

    # Reactivate previous
    result = await _registry.update(previous["id"], {
        "status": "active",
        "rolled_back_at": utc_now().isoformat(),
    })
    logger.warning(f"Model rolled back: {model_name} to v{previous.get('version')}")
    metrics.increment("model_rollback", labels={"model": model_name})
    return result


async def get_active_model(model_name: str) -> Optional[dict]:
    """Get the currently active model version."""
    results = await _registry.find_many(
        filters={"model_name": model_name, "status": "active"}, limit=1
    )
    return results[0] if results else None


async def list_model_versions(model_name: str) -> list[dict]:
    """List all versions of a model."""
    return await _registry.find_many(
        filters={"model_name": model_name},
        limit=50,
        sort_by="updated_at",
        sort_order="desc",
    )
