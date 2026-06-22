"""
generate_ml_manifest.py — Generate docs/_generated/ml-implementation-manifest.json
from the canonical model registry at runtime.

Run via:
    python scripts/generate_ml_manifest.py

Or via repo-doctor-fix which calls this automatically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ML_ROOT = REPO_ROOT / "ML Models" / "aether-ml"
OUTPUT_PATH = REPO_ROOT / "docs" / "_generated" / "ml-implementation-manifest.json"

sys.path.insert(0, str(ML_ROOT))


def _platform_version() -> str:
    """Read version from pyproject.toml — stable for same codebase, matches other generated files."""
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(REPO_ROOT / "pyproject.toml", "rb") as f:
                return tomllib.load(f)["project"]["version"]
        else:
            import tomli
            with open(REPO_ROOT / "pyproject.toml", "rb") as f:
                return tomli.load(f)["project"]["version"]
    except Exception:
        return "unknown"


def _safe(val: object) -> object:
    """Make a value JSON-serialisable."""
    if hasattr(val, "value"):  # enum
        return val.value
    if isinstance(val, (list, tuple)):
        return [_safe(v) for v in val]
    if isinstance(val, dict):
        return {k: _safe(v) for k, v in val.items()}
    return val


def build_manifest() -> dict:
    from common.model_registry import _REGISTRY, list_trainable_models
    from common.feature_contracts import _CONTRACTS

    models = []
    trainable_ids = {m.model_id for m in list_trainable_models()}

    for model_id, entry in _REGISTRY.items():
        contract = _CONTRACTS.get(model_id)
        feature_info: dict = {}
        if contract:
            feature_info = {
                "contract_id": contract.contract_id,
                "schema_version": contract.schema_version,
                "schema_hash": contract.schema_hash,
                "required_count": len(contract.required_features),
                "optional_count": len(contract.optional_features),
                "freshness_sla_seconds": contract.freshness_sla_seconds,
            }

        models.append({
            "model_id": model_id,
            "display_name": entry.display_name,
            "implementation_type": _safe(entry.implementation_type),
            "category": entry.category,
            "task_type": entry.task_type,
            "algorithm": entry.algorithm,
            "tier": _safe(entry.tier),
            "sensitivity_tier": _safe(entry.sensitivity_tier),
            "current_status": _safe(entry.current_status),
            "training_supported": entry.training_supported,
            "serving_supported": entry.serving_supported,
            "batch_supported": entry.batch_supported,
            "batch_requires_privileged": entry.batch_requires_privileged,
            "feature_contract": feature_info,
            "serving_endpoint": entry.serving_endpoint,
            "artifact_format": _safe(entry.artifact_format),
            "artifact_name": entry.artifact_name,
            "minimum_metrics": _safe(entry.minimum_metrics),
            "promotion_requirements": _safe(entry.promotion_requirements),
            "kyber_visible": entry.kyber_visible,
            "tenant_visible": entry.tenant_visible,
            "fail_closed_required": entry.fail_closed_required,
            "owner": entry.owner,
            "docs_slug": entry.docs_slug,
            "deprecated_aliases": _safe(entry.deprecated_aliases),
        })

    return {
        "_generated": True,
        "version": _platform_version(),
        "generated_from": "common/model_registry.py + common/feature_contracts.py",
        "total_models": len(models),
        "trainable_count": len(trainable_ids),
        "models": models,
    }


def _build_content() -> str:
    manifest = build_manifest()
    return json.dumps(manifest, indent=2, default=str) + "\n"


def generate() -> int:
    try:
        content = _build_content()
    except Exception as exc:
        print(f"[FAIL] Could not generate manifest: {exc}", file=sys.stderr)
        return 1
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    manifest = json.loads(content)
    print(f"[OK] Generated {OUTPUT_PATH} ({manifest['total_models']} models)")
    return 0


def check() -> int:
    """Verify committed manifest matches what the registry would generate today."""
    if not OUTPUT_PATH.exists():
        print(
            f"[FAIL] {OUTPUT_PATH} does not exist. "
            "Run: python scripts/generate_ml_manifest.py",
            file=sys.stderr,
        )
        return 1
    try:
        expected_content = _build_content()
    except Exception as exc:
        print(f"[FAIL] Could not build manifest for comparison: {exc}", file=sys.stderr)
        return 1

    actual_content = OUTPUT_PATH.read_text(encoding="utf-8")

    # Compare model entries only (ignore top-level metadata like version that changes on bump)
    try:
        expected_models = json.loads(expected_content).get("models", [])
        actual_models = json.loads(actual_content).get("models", [])
        if expected_models == actual_models:
            print(f"[OK] {OUTPUT_PATH} model content is current.")
            return 0
    except json.JSONDecodeError:
        pass

    print(
        f"[FAIL] {OUTPUT_PATH} is stale. Run: python scripts/generate_ml_manifest.py",
        file=sys.stderr,
    )
    import difflib
    diff = list(difflib.unified_diff(
        actual_content.splitlines(keepends=True),
        expected_content.splitlines(keepends=True),
        fromfile="committed",
        tofile="current-registry",
        n=3,
    ))
    for line in diff[:50]:
        sys.stderr.write(line)
    return 1


def main() -> int:
    if "--check" in sys.argv:
        return check()
    return generate()


if __name__ == "__main__":
    sys.exit(main())
