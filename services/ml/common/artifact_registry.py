"""
Aether ML — Artifact Registry

Manages model artifact lifecycle: save, load, validate, promote, disable,
rollback, and environment-specific loading policy.

Promotion states:
    local      — artifact exists only on developer machine
    trained    — training completed, not yet reviewed
    candidate  — reviewed, ready for staging validation
    staged     — validated in staging, ready for production promotion
    promoted   — active in production
    disabled   — permanently disabled, must not load

Loading rules (enforced):
    local/dev  — may load local/trained/candidate artifacts
    staging    — may load staged/candidate artifacts (synthetic_data MUST be False)
    production — may load promoted artifacts with production_allowed=True
                 and synthetic_data=False ONLY. Fails closed on any violation.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("aether.ml.artifact_registry")

PROMOTION_STATE_ORDER = ["local", "trained", "candidate", "staged", "promoted"]

# Promotion states at/above which governance artifacts must be present.
_GOVERNED_PROMOTION_STATES = ("staged", "promoted")

# Maps a ModelEntry governance flag -> the artifact filename it requires.
GOVERNANCE_ARTIFACT_FILES: dict[str, str] = {
    "requires_model_card": "model_card.json",
    "requires_dataset_card": "dataset_card.json",
    "requires_bias_audit": "bias_audit.json",
    "requires_privacy_review": "privacy_review.json",
    "requires_training_manifest": "training_manifest.json",
}

# A required artifact may be satisfied by any of these on-disk filenames.
# ``dataset_manifest.json`` is written by train.py and satisfies the training
# manifest requirement.
_ARTIFACT_FILE_ALIASES: dict[str, list[str]] = {
    "training_manifest.json": ["training_manifest.json", "dataset_manifest.json"],
}


# ---------------------------------------------------------------------------
# Artifact metadata schema
# ---------------------------------------------------------------------------


@dataclass
class ArtifactMetadata:
    """Immutable provenance record written alongside every saved artifact."""

    model_id: str
    artifact_version: str
    promotion_state: str  # PromotionState values
    artifact_format: str
    artifact_path: str
    checksum_sha256: str
    created_at: str
    created_by: str
    training_run_id: str
    feature_schema_hash: str
    metrics: dict[str, float] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    threshold_passed: bool = False
    synthetic_data: bool = True
    production_allowed: bool = False
    disabled: bool = False
    rollback_from: Optional[str] = None
    notes: str = ""
    hmac_signature: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ArtifactMetadata:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> ArtifactMetadata:
        d = json.loads(path.read_text())
        return cls.from_dict(d)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ArtifactError(RuntimeError):
    """Base class for artifact registry errors."""


class ArtifactNotFound(ArtifactError):
    """Raised when no artifact can be located."""


class ArtifactChecksumMismatch(ArtifactError):
    """Raised when the stored checksum does not match the actual file."""


class ArtifactPromotionError(ArtifactError):
    """Raised when a promotion policy is violated."""


class ArtifactLoadingPolicyError(ArtifactError):
    """Raised when the environment policy forbids loading an artifact."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_env() -> str:
    return os.getenv("AETHER_ENV", "local").lower()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


def save_artifact(
    model_id: str,
    artifact_path: Path,
    *,
    artifact_version: str,
    promotion_state: str = "trained",
    artifact_format: str = "joblib",
    training_run_id: str = "",
    feature_schema_hash: str = "",
    metrics: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    threshold_passed: bool = False,
    synthetic_data: bool = True,
    notes: str = "",
    created_by: str = "training-pipeline",
) -> ArtifactMetadata:
    """
    Write artifact metadata alongside an already-saved artifact file.

    Args:
        model_id: Canonical model ID.
        artifact_path: Path to the artifact file (e.g. model.joblib).
        artifact_version: Version string (e.g. "v1_20240601_120000").
        promotion_state: Initial promotion state.
        ...

    Returns:
        ArtifactMetadata written to {artifact_path.parent}/metadata.json.
    """
    if not artifact_path.exists():
        raise ArtifactNotFound(f"Artifact file not found: {artifact_path}")

    checksum = _sha256_file(artifact_path)
    signing_key = os.getenv("ARTIFACT_SIGNING_KEY", "")
    env = _current_env()
    if signing_key:
        hmac_sig: Optional[str] = _hmac.new(
            signing_key.encode(), msg=checksum.encode(), digestmod=hashlib.sha256
        ).hexdigest()
    elif env in ("staging", "stage", "production", "prod"):
        raise ArtifactError(
            "ARTIFACT_SIGNING_KEY must be set in staging/production environments"
        )
    else:
        hmac_sig = None

    production_allowed = (
        not synthetic_data
        and threshold_passed
        and promotion_state == "promoted"
    )

    metadata = ArtifactMetadata(
        model_id=model_id,
        artifact_version=artifact_version,
        promotion_state=promotion_state,
        artifact_format=artifact_format,
        artifact_path=str(artifact_path),
        checksum_sha256=checksum,
        created_at=datetime.now(timezone.utc).isoformat(),
        created_by=created_by,
        training_run_id=training_run_id,
        feature_schema_hash=feature_schema_hash,
        metrics=metrics or {},
        thresholds=thresholds or {},
        threshold_passed=threshold_passed,
        synthetic_data=synthetic_data,
        production_allowed=production_allowed,
        notes=notes,
        hmac_signature=hmac_sig,
    )

    meta_path = artifact_path.parent / "metadata.json"
    metadata.save(meta_path)
    logger.info(
        "Artifact metadata saved: model=%s version=%s state=%s synthetic=%s",
        model_id, artifact_version, promotion_state, synthetic_data,
    )
    return metadata


def load_artifact(
    artifact_dir: Path,
    env: str | None = None,
) -> tuple[Path, ArtifactMetadata]:
    """
    Load and validate an artifact from a directory.

    Args:
        artifact_dir: Directory containing the artifact and metadata.json.
        env: Environment override. Defaults to AETHER_ENV.

    Returns:
        (artifact_path, metadata)

    Raises:
        ArtifactNotFound: If artifact or metadata is missing.
        ArtifactChecksumMismatch: If checksum does not match.
        ArtifactLoadingPolicyError: If environment policy forbids loading.
    """
    env = (env or _current_env()).lower()

    meta_path = artifact_dir / "metadata.json"
    if not meta_path.exists():
        raise ArtifactNotFound(
            f"Artifact metadata not found at {meta_path}. "
            "All model artifacts must include a metadata.json."
        )

    metadata = ArtifactMetadata.load(meta_path)
    _enforce_load_policy(metadata, env)

    artifact_path = Path(metadata.artifact_path)
    if not artifact_path.exists():
        # Try relative to artifact_dir
        artifact_path = artifact_dir / Path(metadata.artifact_path).name
        if not artifact_path.exists():
            raise ArtifactNotFound(
                f"Artifact file not found: {metadata.artifact_path} "
                f"(also tried {artifact_path})"
            )

    actual_checksum = _sha256_file(artifact_path)
    if actual_checksum != metadata.checksum_sha256:
        raise ArtifactChecksumMismatch(
            f"Checksum mismatch for {artifact_path}: "
            f"expected {metadata.checksum_sha256}, got {actual_checksum}"
        )

    signing_key = os.getenv("ARTIFACT_SIGNING_KEY", "")
    if signing_key and metadata.hmac_signature:
        expected_sig = _hmac.new(
            signing_key.encode(),
            msg=metadata.checksum_sha256.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not _hmac.compare_digest(expected_sig, metadata.hmac_signature):
            raise ArtifactChecksumMismatch(
                f"HMAC signature mismatch for {artifact_path}: artifact may have been tampered"
            )
    elif env in ("staging", "stage", "production", "prod") and not signing_key:
        raise ArtifactLoadingPolicyError(
            "ARTIFACT_SIGNING_KEY must be set in staging/production environments"
        )

    logger.info(
        "Artifact loaded: model=%s version=%s state=%s env=%s",
        metadata.model_id, metadata.artifact_version,
        metadata.promotion_state, env,
    )
    return artifact_path, metadata


def validate_artifact(artifact_dir: Path, env: str | None = None) -> ArtifactMetadata:
    """Validate artifact without loading the model object. Returns metadata."""
    _, metadata = load_artifact(artifact_dir, env=env)
    return metadata


def list_artifacts(model_root: Path, model_id: str) -> list[ArtifactMetadata]:
    """List all artifact versions for a model, sorted newest-first."""
    model_dir = model_root / model_id
    if not model_dir.exists():
        return []

    artifacts: list[ArtifactMetadata] = []
    for version_dir in sorted(model_dir.iterdir(), reverse=True):
        meta_path = version_dir / "metadata.json"
        if meta_path.exists():
            try:
                artifacts.append(ArtifactMetadata.load(meta_path))
            except Exception as exc:
                logger.warning("Skipping corrupt metadata at %s: %s", meta_path, exc)

    return artifacts


def required_promotion_artifacts(model_id: str) -> list[str]:
    """Return the governance artifact filenames required to promote ``model_id``.

    Derived from the model's ``ModelEntry`` governance flags in
    ``common.model_registry``. Returns an empty list for unknown models or
    models with no governance requirements. Model-registry import failures are
    swallowed so this stays usable in lightweight environments.
    """
    try:
        from common.model_registry import get_model, resolve_model_id
    except Exception:  # pragma: no cover - registry always importable in practice
        return []

    canonical = resolve_model_id(model_id) or model_id
    entry = get_model(canonical)
    if entry is None:
        return []

    required: list[str] = []
    for flag, filename in GOVERNANCE_ARTIFACT_FILES.items():
        if getattr(entry, flag, False):
            required.append(filename)
    return required


def _missing_governance_artifacts(artifact_dir: Path, model_id: str) -> list[str]:
    """Return required governance artifacts that are absent from ``artifact_dir``."""
    missing: list[str] = []
    for filename in required_promotion_artifacts(model_id):
        candidates = _ARTIFACT_FILE_ALIASES.get(filename, [filename])
        if not any((artifact_dir / candidate).exists() for candidate in candidates):
            missing.append(filename)
    return missing


def _production_promotion_allowed(model_id: str) -> bool:
    """Return whether the registry permits promoting ``model_id`` to production."""
    try:
        from common.model_registry import get_model, resolve_model_id
    except Exception:  # pragma: no cover
        return True
    canonical = resolve_model_id(model_id) or model_id
    entry = get_model(canonical)
    if entry is None:
        return True
    return getattr(entry, "production_promotion_allowed", True)


def write_promotion_artifacts(
    artifact_dir: Path,
    model_id: str,
    *,
    model: Any = None,
    X: Any = None,
    y: Any = None,
    sensitive_features: list[str] | None = None,
    model_card: dict[str, Any] | None = None,
    dataset_card: dict[str, Any] | None = None,
    privacy_review: dict[str, Any] | None = None,
    training_manifest: dict[str, Any] | None = None,
    bias_audit_result: dict[str, Any] | None = None,
    created_by: str = "training-pipeline",
) -> dict[str, Path]:
    """Write the governance artifacts required to promote ``model_id``.

    Only the artifacts the model actually requires (per its registry governance
    flags) are written, unless an explicit payload is supplied for one. Each
    artifact is written atomically as ``<name>.json`` into ``artifact_dir``.

    For the bias audit: if ``bias_audit_result`` is not supplied but a fitted
    ``model`` plus ``X``, ``y`` and ``sensitive_features`` are, this runs
    ``training.pipelines.evaluation.ModelEvaluator.bias_audit`` (imported lazily
    so this module stays importable without the ML runtime) to produce it.

    Returns a mapping of ``{filename: written_path}`` for the artifacts written.
    """
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    required = set(required_promotion_artifacts(model_id))
    written: dict[str, Path] = {}
    now = datetime.now(timezone.utc).isoformat()

    def _write(filename: str, payload: dict[str, Any]) -> None:
        path = artifact_dir / filename
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, path)
        written[filename] = path

    if "model_card.json" in required:
        payload = model_card or {
            "model_id": model_id,
            "created_at": now,
            "created_by": created_by,
            "summary": "Auto-generated placeholder model card. Review before promotion.",
        }
        _write("model_card.json", payload)

    if "dataset_card.json" in required:
        payload = dataset_card or {
            "model_id": model_id,
            "created_at": now,
            "created_by": created_by,
            "summary": "Auto-generated placeholder dataset card. Review before promotion.",
        }
        _write("dataset_card.json", payload)

    if "privacy_review.json" in required:
        payload = privacy_review or {
            "model_id": model_id,
            "created_at": now,
            "created_by": created_by,
            "status": "pending_review",
            "summary": "Auto-generated placeholder privacy review. Review before promotion.",
        }
        _write("privacy_review.json", payload)

    if "training_manifest.json" in required and training_manifest is not None:
        _write("training_manifest.json", training_manifest)

    if "bias_audit.json" in required:
        payload = bias_audit_result
        if payload is None and model is not None and X is not None and y is not None:
            from training.pipelines.evaluation import ModelEvaluator

            evaluator = ModelEvaluator()
            payload = evaluator.bias_audit(
                model, X, y, sensitive_features or []
            )
        if payload is None:
            payload = {
                "model_id": model_id,
                "created_at": now,
                "created_by": created_by,
                "overall_fairness_pass": None,
                "summary": (
                    "Auto-generated placeholder bias audit. Provide a fitted "
                    "model plus data or an explicit bias_audit_result."
                ),
            }
        else:
            payload = {"model_id": model_id, "created_at": now, **payload}
        _write("bias_audit.json", payload)

    return written


def validate_promotion(artifact_dir: Path, new_state: str) -> ArtifactMetadata:
    """
    Validate that an artifact is eligible for promotion to ``new_state``
    WITHOUT mutating anything.

    Runs every governance/promotion gate that :func:`promote_artifact` enforces
    (disabled state, synthetic-data ban, threshold gate, registry production
    permission, required governance artifacts, state ordering) and raises
    :class:`ArtifactPromotionError` / :class:`ArtifactNotFound` on the first
    violation. Returns the artifact's current metadata on success.

    Use this to gate side effects (e.g. S3 uploads) BEFORE they happen.
    """
    meta_path = artifact_dir / "metadata.json"
    if not meta_path.exists():
        raise ArtifactNotFound(f"No metadata at {artifact_dir}")

    metadata = ArtifactMetadata.load(meta_path)

    if metadata.disabled:
        raise ArtifactPromotionError(
            f"Cannot promote disabled artifact: {metadata.artifact_version}"
        )

    if new_state == "promoted" and metadata.synthetic_data:
        raise ArtifactPromotionError(
            f"Cannot promote synthetic artifact to production: {metadata.model_id} "
            f"version={metadata.artifact_version}. "
            "Only real-data trained artifacts may be promoted."
        )

    if new_state == "promoted" and not metadata.threshold_passed:
        raise ArtifactPromotionError(
            f"Cannot promote artifact that did not pass metric thresholds: "
            f"{metadata.model_id} version={metadata.artifact_version}"
        )

    if new_state == "promoted" and not _production_promotion_allowed(metadata.model_id):
        raise ArtifactPromotionError(
            f"Model '{metadata.model_id}' is not permitted to be promoted to "
            "production (production_promotion_allowed=False in the model registry)."
        )

    if new_state in _GOVERNED_PROMOTION_STATES:
        missing = _missing_governance_artifacts(artifact_dir, metadata.model_id)
        if missing:
            raise ArtifactPromotionError(
                f"Cannot promote {metadata.model_id} version={metadata.artifact_version} "
                f"to '{new_state}': missing required governance artifacts: {missing}. "
                "Generate them (see write_promotion_artifacts) before promotion."
            )

    current_idx = PROMOTION_STATE_ORDER.index(metadata.promotion_state) if metadata.promotion_state in PROMOTION_STATE_ORDER else -1
    new_idx = PROMOTION_STATE_ORDER.index(new_state) if new_state in PROMOTION_STATE_ORDER else -1

    if new_idx < current_idx:
        raise ArtifactPromotionError(
            f"Cannot downgrade promotion state from '{metadata.promotion_state}' to '{new_state}'. "
            "Use rollback_artifact() to roll back."
        )

    return metadata


def promote_artifact(
    artifact_dir: Path,
    new_state: str,
    promoted_by: str = "system",
) -> ArtifactMetadata:
    """
    Promote an artifact to a new state.

    Rules (enforced by :func:`validate_promotion`):
    - Cannot promote disabled artifacts.
    - Cannot promote synthetic_data=True artifacts to production.
    - States must advance (no downgrade except via rollback).
    - Promoting to ``staged``/``promoted`` requires the model's governance
      artifacts (model card, dataset card, bias audit, privacy review, training
      manifest) to be present per its registry governance flags.
    """
    metadata = validate_promotion(artifact_dir, new_state)
    meta_path = artifact_dir / "metadata.json"

    from_state = metadata.promotion_state
    metadata.promotion_state = new_state
    if new_state == "promoted":
        metadata.production_allowed = True
    metadata.save(meta_path)

    _append_promotion_audit(
        artifact_dir.parent,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "promote",
            "from_state": from_state,
            "to_state": new_state,
            "artifact_version": metadata.artifact_version,
            "actor": promoted_by,
            "metrics": metadata.metrics,
        },
    )
    logger.info(
        "Artifact promoted: model=%s version=%s %s -> %s",
        metadata.model_id, metadata.artifact_version, from_state, new_state,
    )
    return metadata


def disable_artifact(artifact_dir: Path, reason: str = "") -> ArtifactMetadata:
    """Mark an artifact as disabled. Disabled artifacts never load."""
    meta_path = artifact_dir / "metadata.json"
    if not meta_path.exists():
        raise ArtifactNotFound(f"No metadata at {artifact_dir}")

    metadata = ArtifactMetadata.load(meta_path)
    metadata.disabled = True
    metadata.promotion_state = "disabled"
    metadata.production_allowed = False
    metadata.notes += f" | DISABLED: {reason} at {datetime.now(timezone.utc).isoformat()}"
    metadata.save(meta_path)

    logger.warning(
        "Artifact DISABLED: model=%s version=%s reason=%s",
        metadata.model_id, metadata.artifact_version, reason,
    )
    return metadata


def rollback_artifact(
    model_root: Path,
    model_id: str,
    env: str | None = None,
) -> Optional[ArtifactMetadata]:
    """
    Roll back to the previous promoted artifact.

    Writes ``active_artifact.json`` in the model directory so that
    ``resolve_active_artifact`` picks the rollback target on the next load.
    Appends a rollback record to ``promotion_audit.jsonl``.

    Returns the metadata of the rollback target, or None if there is no
    previous promoted version to roll back to.
    """
    artifacts = list_artifacts(model_root, model_id)

    valid = [
        m for m in artifacts
        if m.promotion_state == "promoted"
        and not m.disabled
        and m.production_allowed
    ]

    if len(valid) < 2:
        logger.warning(
            "No previous promoted artifact for rollback: model=%s", model_id
        )
        return None

    # artifacts is newest-first; valid[0] = current, valid[1] = rollback target
    current = valid[0]
    target = valid[1]
    model_dir = model_root / model_id

    # Atomically write the active pointer so resolve_active_artifact uses it
    active_ptr = model_dir / "active_artifact.json"
    tmp_ptr = active_ptr.with_suffix(".tmp")
    tmp_ptr.write_text(
        json.dumps(
            {
                "version": target.artifact_version,
                "rollback_from": current.artifact_version,
                "rolled_back_at": datetime.now(timezone.utc).isoformat(),
            },
            default=str,
        )
    )
    os.replace(tmp_ptr, active_ptr)

    _append_promotion_audit(
        model_dir,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "rollback",
            "from_state": current.artifact_version,
            "to_state": target.artifact_version,
            "artifact_version": target.artifact_version,
            "actor": "system",
            "metrics": target.metrics,
        },
    )
    logger.info(
        "Artifact rolled back: model=%s %s -> %s",
        model_id, current.artifact_version, target.artifact_version,
    )
    return target


def resolve_active_artifact(
    model_root: Path,
    model_id: str,
    env: str | None = None,
) -> Optional[Path]:
    """
    Return the artifact directory of the active artifact for this model/env.

    Returns None if no suitable artifact is found (caller must handle fail-closed).
    """
    env = (env or _current_env()).lower()
    model_dir = model_root / model_id

    # If a rollback pointer is present, honour it before scanning all versions
    active_ptr = model_dir / "active_artifact.json"
    if active_ptr.exists():
        try:
            ptr = json.loads(active_ptr.read_text())
            pinned_version = ptr.get("version")
            if pinned_version:
                for version_dir in model_dir.iterdir():
                    if version_dir.name == pinned_version:
                        meta_path = version_dir / "metadata.json"
                        if meta_path.exists():
                            meta = ArtifactMetadata.load(meta_path)
                            artifact_file = Path(meta.artifact_path)
                            if not artifact_file.exists():
                                artifact_file = version_dir / Path(meta.artifact_path).name
                            if artifact_file.exists():
                                return artifact_file.parent
        except Exception as exc:
            logger.warning("Failed to read active_artifact.json for %s: %s", model_id, exc)

    artifacts = list_artifacts(model_root, model_id)

    allowed_states = _allowed_states_for_env(env)

    for meta in artifacts:
        if meta.disabled:
            continue
        if meta.promotion_state not in allowed_states:
            continue
        if env in ("production", "prod"):
            if not meta.production_allowed or meta.synthetic_data:
                continue
        elif env in ("staging", "stage"):
            if meta.synthetic_data:
                continue

        artifact_file = Path(meta.artifact_path)
        if not artifact_file.exists():
            artifact_dir = model_root / model_id / _version_dir_from_path(meta.artifact_path)
            artifact_file = artifact_dir / Path(meta.artifact_path).name

        if artifact_file.exists():
            return artifact_file.parent

    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _enforce_load_policy(metadata: ArtifactMetadata, env: str) -> None:
    """Raise ArtifactLoadingPolicyError if loading is forbidden in this env."""
    if metadata.disabled:
        raise ArtifactLoadingPolicyError(
            f"Artifact is disabled: model={metadata.model_id} "
            f"version={metadata.artifact_version}"
        )

    allowed = _allowed_states_for_env(env)
    if metadata.promotion_state not in allowed:
        raise ArtifactLoadingPolicyError(
            f"Artifact state '{metadata.promotion_state}' is not allowed in env='{env}'. "
            f"Allowed states: {allowed}"
        )

    if env in ("production", "prod"):
        if not metadata.production_allowed:
            raise ArtifactLoadingPolicyError(
                f"Artifact is not production_allowed: model={metadata.model_id} "
                f"version={metadata.artifact_version}. "
                "Only promoted, real-data, threshold-passing artifacts are production-allowed."
            )
        if metadata.synthetic_data:
            raise ArtifactLoadingPolicyError(
                f"Synthetic artifact cannot be loaded in production: "
                f"model={metadata.model_id} version={metadata.artifact_version}"
            )

    if env in ("staging", "stage"):
        if metadata.synthetic_data:
            raise ArtifactLoadingPolicyError(
                f"Synthetic artifact cannot be loaded in staging: "
                f"model={metadata.model_id} version={metadata.artifact_version}. "
                "Staging requires real sampled data."
            )


def _allowed_states_for_env(env: str) -> set[str]:
    if env in ("production", "prod"):
        return {"promoted"}
    if env in ("staging", "stage"):
        return {"staged", "candidate", "promoted"}
    # local / development / test — allow everything non-disabled
    return {"local", "trained", "candidate", "staged", "promoted"}


def _append_promotion_audit(model_dir: Path, record: dict[str, Any]) -> None:
    """Append a single JSON line to the model's promotion audit log."""
    audit_path = model_dir / "promotion_audit.jsonl"
    with open(audit_path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _version_dir_from_path(artifact_path: str) -> str:
    """Extract version directory name from artifact path (best-effort)."""
    parts = Path(artifact_path).parts
    for i, part in enumerate(parts):
        if part.startswith("v1_") or part.startswith("v2_"):
            return part
    return parts[-2] if len(parts) >= 2 else ""
