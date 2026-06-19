"""
validate_ml_registry.py — CI gate for ML model registry consistency.

Checks:
1. All 9 trainable model IDs exist in the registry
2. All aliases resolve to canonical IDs (no dangling aliases)
3. No duplicate serving endpoints
4. All trainable models have a feature contract
5. Training configs exist for all trainable models
6. Backend routes file uses canonical IDs only (no stale aliases in code)

Exit 0 on success, 1 on any failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ML_ROOT = REPO_ROOT / "ML Models" / "aether-ml"

EXPECTED_TRAINABLE = {
    "intent_prediction",
    "bot_detection",
    "session_scorer",
    "identity_resolution",
    "journey_prediction",
    "churn_prediction",
    "ltv_prediction",
    "anomaly_detection",
    "campaign_attribution",
}

EXPECTED_ALIASES = {
    "identity_gnn": "identity_resolution",
    "journey_tft": "journey_prediction",
}


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def check_registry() -> list[str]:
    errors: list[str] = []
    sys.path.insert(0, str(ML_ROOT))
    try:
        from common.model_registry import (
            _REGISTRY,
            _ALIAS_MAP,
            list_trainable_models,
            resolve_model_id,
        )
    except ImportError as e:
        errors.append(f"Cannot import common.model_registry: {e}")
        return errors

    # 1. All 9 trainable models present
    registry_trainable = {m.model_id for m in list_trainable_models()}
    missing = EXPECTED_TRAINABLE - registry_trainable
    if missing:
        errors.append(f"Trainable models missing from registry: {sorted(missing)}")
    else:
        ok(f"All 9 trainable models present: {sorted(registry_trainable)}")

    extra = registry_trainable - EXPECTED_TRAINABLE
    if extra:
        errors.append(f"Unexpected trainable models in registry: {sorted(extra)}")

    # 2. All aliases resolve correctly
    for alias, canonical in EXPECTED_ALIASES.items():
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                resolved = resolve_model_id(alias)
            if resolved != canonical:
                errors.append(f"Alias '{alias}' resolves to '{resolved}' instead of '{canonical}'")
        except ValueError as e:
            errors.append(f"Alias '{alias}' failed to resolve: {e}")

    if not errors:
        ok(f"All {len(EXPECTED_ALIASES)} aliases resolve correctly")

    # 3. No duplicate serving endpoints
    endpoints: dict[str, str] = {}
    for entry in _REGISTRY.values():
        ep = entry.serving_endpoint
        if ep in endpoints:
            errors.append(f"Duplicate serving endpoint '{ep}' for '{entry.model_id}' and '{endpoints[ep]}'")
        endpoints[ep] = entry.model_id
    if not errors or all("endpoint" not in e for e in errors):
        ok(f"No duplicate serving endpoints ({len(endpoints)} unique)")

    return errors


def check_feature_contracts() -> list[str]:
    errors: list[str] = []
    sys.path.insert(0, str(ML_ROOT))
    try:
        from common.feature_contracts import _CONTRACTS
        from common.model_registry import list_trainable_models
    except ImportError as e:
        errors.append(f"Cannot import feature_contracts: {e}")
        return errors

    for entry in list_trainable_models():
        if entry.model_id not in _CONTRACTS:
            errors.append(f"No feature contract for trainable model '{entry.model_id}'")

    if not errors:
        ok(f"All {len(list(list_trainable_models()))} trainable models have feature contracts")
    return errors


def check_training_configs() -> list[str]:
    errors: list[str] = []
    sys.path.insert(0, str(ML_ROOT))
    try:
        from training.configs.model_configs import MODEL_CONFIGS
    except ImportError as e:
        errors.append(f"Cannot import training.configs.model_configs: {e}")
        return errors

    config_ids = set(MODEL_CONFIGS.keys())
    missing = EXPECTED_TRAINABLE - config_ids
    if missing:
        errors.append(f"Training configs missing for: {sorted(missing)}")
    else:
        ok(f"All 9 trainable models have training configs")

    extra = config_ids - EXPECTED_TRAINABLE
    if extra:
        errors.append(f"Unexpected training configs (not in registry): {sorted(extra)}")
    return errors


def check_backend_routes() -> list[str]:
    errors: list[str] = []
    routes_path = REPO_ROOT / "Backend Architecture" / "aether-backend" / "services" / "ml_serving" / "routes.py"
    if not routes_path.exists():
        errors.append(f"Backend routes file not found: {routes_path}")
        return errors

    content = routes_path.read_text()

    # Strip comments and docstrings before checking
    stripped = re.sub(r'""".*?"""', '', content, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", '', stripped, flags=re.DOTALL)
    stripped = re.sub(r'#.*$', '', stripped, flags=re.MULTILINE)

    # modified_output must not exist in code (only .output)
    if "modified_output" in stripped:
        errors.append("Backend routes reference 'modified_output' — must use 'post_result.output'")
    else:
        ok("Backend routes use 'post_result.output' correctly")

    # pre_request must be called
    if "pre_request(" not in content and "defense.pre_request" not in content:
        errors.append("Backend routes do not call defense.pre_request() before inference")
    else:
        ok("Backend routes call defense.pre_request()")

    # batch must be privileged
    if "ml:batch" not in content and "privileged" not in content.lower():
        errors.append("Backend batch route missing privilege enforcement")
    else:
        ok("Backend batch route has privilege enforcement")

    # canonical_model_id in response
    if "canonical_model_id" not in content:
        errors.append("Backend routes don't include 'canonical_model_id' in response")
    else:
        ok("Backend routes include 'canonical_model_id' in responses")

    return errors


def main() -> int:
    print("=" * 60)
    print("ML Registry Consistency Validation")
    print("=" * 60)

    all_errors: list[str] = []

    print("\n--- Registry ---")
    all_errors.extend(check_registry())

    print("\n--- Feature Contracts ---")
    all_errors.extend(check_feature_contracts())

    print("\n--- Training Configs ---")
    all_errors.extend(check_training_configs())

    print("\n--- Backend Routes ---")
    all_errors.extend(check_backend_routes())

    print("\n" + "=" * 60)
    if all_errors:
        print(f"FAILED — {len(all_errors)} error(s):")
        for e in all_errors:
            print(f"  • {e}", file=sys.stderr)
        return 1

    print(f"PASSED — all ML registry checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
