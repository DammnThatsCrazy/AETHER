"""Runtime loader/applier for training-time preprocessing artifacts.

The training pipeline (``training/pipelines/train.py``) persists the fitted
preprocessing pipeline as ``preprocessing.joblib`` plus ``preprocessing_meta.json``
(clip bounds + feature order) alongside every model artifact. This module is
the single serving-side consumer of those files: edge models, server models,
and ONNX wrappers load the fitted preprocessing here and apply it before
inference so serving inputs are on the exact feature scale seen at training
time (clip -> median-impute -> standardize), instead of a raw ``fillna(0)``.

Also verifies the artifact's feature-schema hash against the canonical feature
contract at load time (fail-closed on mismatch).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger("aether.ml.artifact_preprocessing")


class FeatureSchemaMismatch(ValueError):
    """Raised when an artifact's feature schema hash does not match the contract."""


def _expected_schema_hash(model_id: str) -> str:
    """Return the canonical contract schema hash for ``model_id`` ("" if unavailable)."""
    try:
        from common.feature_contracts import compute_schema_hash
        return compute_schema_hash(model_id)
    except Exception:
        return ""


def verify_feature_schema_hash(artifact_dir: Path, model_id: str) -> None:
    """Verify the artifact's recorded feature schema hash against the contract.

    Reads ``feature_schema_hash`` from the artifact's ``metadata.json`` and
    compares it to the canonical contract hash for ``model_id``. Raises
    :class:`FeatureSchemaMismatch` when both hashes are non-empty and differ.
    Empty hashes (legacy/synthetic artifacts, or contracts unavailable) are
    logged and tolerated.
    """
    meta_path = Path(artifact_dir) / "metadata.json"
    recorded = ""
    if meta_path.exists():
        try:
            recorded = str(json.loads(meta_path.read_text()).get("feature_schema_hash", "") or "")
        except Exception as exc:
            logger.warning("Unreadable metadata.json at %s: %s", meta_path, exc)

    expected = _expected_schema_hash(model_id)
    if recorded and expected and recorded != expected:
        raise FeatureSchemaMismatch(
            f"Feature schema hash mismatch for model '{model_id}' at {artifact_dir}: "
            f"artifact={recorded} contract={expected}. The artifact was trained "
            "against a different feature contract and must not be served."
        )
    if not recorded or not expected:
        logger.debug(
            "Feature schema hash verification skipped for %s (artifact=%r, contract=%r)",
            model_id, recorded, expected,
        )


@dataclass
class ArtifactPreprocessing:
    """A fitted, training-time preprocessing bundle ready to apply at serve time."""

    pipeline: Any  # fitted sklearn ColumnTransformer
    feature_order: list[str]
    clip_bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    feature_schema_hash: str = ""

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply the trained preprocessing to a raw feature frame.

        Columns are reindexed to the training feature order — missing columns
        become NaN so the trained median imputer fills them (identical to
        training-time handling), rather than an arbitrary ``fillna(0)``.
        """
        Xf = X.reindex(columns=self.feature_order)
        for col, bounds in self.clip_bounds.items():
            if col in Xf.columns:
                Xf[col] = Xf[col].clip(lower=bounds[0], upper=bounds[1])
        arr = self.pipeline.transform(Xf)
        return pd.DataFrame(arr, columns=self.feature_order, index=X.index)


def _feature_order_from_pipeline(pipeline: Any) -> list[str]:
    """Best-effort recovery of feature order from a fitted ColumnTransformer."""
    try:
        cols: list[str] = []
        for _name, _trans, columns in pipeline.transformers_:
            if _name == "remainder":
                continue
            cols.extend(list(columns))
        if cols:
            return cols
    except Exception:
        pass
    try:
        return list(pipeline.feature_names_in_)
    except Exception:
        return []


def load_artifact_preprocessing(
    artifact_dir: Path | str,
    model_id: Optional[str] = None,
) -> Optional[ArtifactPreprocessing]:
    """Load the fitted training-time preprocessing bundle from an artifact dir.

    Returns None when ``preprocessing.joblib`` is absent (legacy artifacts or
    models trained outside the unified pipeline) — callers fall back to their
    historical behavior in that case.

    When ``model_id`` is given, the artifact's feature schema hash is verified
    against the canonical feature contract; a mismatch raises
    :class:`FeatureSchemaMismatch` (fail closed).
    """
    artifact_dir = Path(artifact_dir)
    preprocessing_path = artifact_dir / "preprocessing.joblib"
    if not preprocessing_path.exists():
        return None

    if model_id:
        verify_feature_schema_hash(artifact_dir, model_id)

    import joblib

    pipeline = joblib.load(preprocessing_path)

    clip_bounds: dict[str, tuple[float, float]] = {}
    feature_order: list[str] = []
    meta_path = artifact_dir / "preprocessing_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            clip_bounds = {
                col: (float(lo), float(hi))
                for col, (lo, hi) in (meta.get("clip_bounds") or {}).items()
            }
            feature_order = list(meta.get("feature_order") or [])
        except Exception as exc:
            logger.warning("Unreadable preprocessing_meta.json at %s: %s", meta_path, exc)

    if not feature_order:
        feature_order = _feature_order_from_pipeline(pipeline)
    if not feature_order:
        logger.warning(
            "Cannot determine feature order for preprocessing at %s — skipping",
            artifact_dir,
        )
        return None

    schema_hash = ""
    metadata_path = artifact_dir / "metadata.json"
    if metadata_path.exists():
        try:
            schema_hash = str(
                json.loads(metadata_path.read_text()).get("feature_schema_hash", "") or ""
            )
        except Exception:
            schema_hash = ""

    logger.info(
        "Loaded training-time preprocessing for %s from %s (%d features)",
        model_id or "<unknown>", artifact_dir, len(feature_order),
    )
    return ArtifactPreprocessing(
        pipeline=pipeline,
        feature_order=feature_order,
        clip_bounds=clip_bounds,
        feature_schema_hash=schema_hash,
    )
