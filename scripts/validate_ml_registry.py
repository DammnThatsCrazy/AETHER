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
            errors.append(
                f"Duplicate serving endpoint '{ep}' for '{entry.model_id}' and '{endpoints[ep]}'"
            )
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

    trainable = list(list_trainable_models())
    for entry in trainable:
        if entry.model_id not in _CONTRACTS:
            errors.append(f"No feature contract for trainable model '{entry.model_id}'")

    # Check for duplicate contract IDs
    seen_contract_ids: dict[str, str] = {}
    for cid, contract in _CONTRACTS.items():
        if cid in seen_contract_ids:
            errors.append(f"Duplicate contract ID '{cid}'")
        seen_contract_ids[cid] = cid

    if not errors:
        ok(f"All {len(trainable)} trainable models have feature contracts, no duplicates")
    return errors


def check_serving_endpoints() -> list[str]:
    """Verify each registry serving endpoint exists in the FastAPI route table."""
    errors: list[str] = []
    serving_api_path = ML_ROOT / "serving" / "src" / "api.py"
    if not serving_api_path.exists():
        errors.append(f"Serving API not found: {serving_api_path}")
        return errors

    content = serving_api_path.read_text()
    sys.path.insert(0, str(ML_ROOT))
    try:
        from common.model_registry import list_trainable_models, get_model
    except ImportError as e:
        errors.append(f"Cannot import model_registry for endpoint check: {e}")
        return errors

    # Verify anomaly_detection uses dedicated endpoint, not batch
    anomaly = get_model("anomaly_detection")
    if anomaly and "/v1/predict/batch" in anomaly.serving_endpoint:
        errors.append(
            "anomaly_detection.serving_endpoint must be '/v1/predict/anomaly', "
            f"not '{anomaly.serving_endpoint}'"
        )

    # Verify each serving endpoint appears in the API file as a route decorator
    for entry in list_trainable_models():
        ep = entry.serving_endpoint
        if not ep:
            continue
        # Check for @router.post("/v1/predict/...") or @app.post(...)
        if f'"{ep}"' not in content and f"'{ep}'" not in content:
            errors.append(
                f"Serving endpoint '{ep}' for '{entry.model_id}' not found "
                f"as a route in serving/src/api.py"
            )

    if not errors:
        ok("All trainable-model serving endpoints exist in serving/src/api.py")
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
    routes_path = (
        REPO_ROOT
        / "Backend Architecture"
        / "aether-backend"
        / "services"
        / "ml_serving"
        / "routes.py"
    )
    if not routes_path.exists():
        errors.append(f"Backend routes file not found: {routes_path}")
        return errors

    content = routes_path.read_text()

    # Strip comments and docstrings before checking
    stripped = re.sub(r'""".*?"""', "", content, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"#.*$", "", stripped, flags=re.MULTILINE)

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


def check_no_authored_model_lists() -> list[str]:
    """Serving API must not define MODEL_NAMES or MODEL_TYPES as authored literal constants."""
    import ast

    errors: list[str] = []
    serving_api = ML_ROOT / "serving" / "src" / "api.py"
    if not serving_api.exists():
        errors.append(f"Serving API file not found: {serving_api}")
        return errors

    try:
        tree = ast.parse(serving_api.read_text())
    except SyntaxError as e:
        errors.append(f"SyntaxError parsing serving/src/api.py: {e}")
        return errors

    # Only check top-level assignments — except-block fallbacks are intentional.
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id in ("MODEL_NAMES", "MODEL_TYPES") and isinstance(
                node.value, (ast.List, ast.Dict)
            ):
                errors.append(
                    f"serving/src/api.py:{node.lineno} — '{target.id}' is an authored literal. "
                    "It must be derived from common.model_registry."
                )

    if not errors:
        ok("No authored MODEL_NAMES/MODEL_TYPES literals in serving/src/api.py")
    return errors


def check_model_type_enum() -> list[str]:
    """ModelType enum in common/src/base.py must contain all registry models.

    Parse ``base.py`` instead of importing it so this consistency gate can run
    in lightweight repo-health jobs before optional ML runtime packages (for
    example joblib/sklearn) are available. The registry itself is intentionally
    lightweight and remains the canonical source for model IDs.
    """
    import ast

    errors: list[str] = []
    base_file = ML_ROOT / "common" / "src" / "base.py"
    if not base_file.exists():
        errors.append(f"ModelType source not found: {base_file}")
        return errors

    try:
        tree = ast.parse(base_file.read_text())
        from common.model_registry import list_models
    except (ImportError, SyntaxError) as e:
        errors.append(f"Cannot parse ModelType or import model_registry: {e}")
        return errors

    enum_values: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "ModelType":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                enum_values.add(stmt.value.value)
        break
    else:
        errors.append("ModelType not found in common/src/base.py")
        return errors

    registry_ids = {m.model_id for m in list_models()}
    missing = registry_ids - enum_values
    if missing:
        errors.append(
            f"ModelType enum missing entries: {sorted(missing)}. "
            "Add to ML Models/aether-ml/common/src/base.py."
        )
    else:
        ok(f"ModelType enum covers all {len(registry_ids)} registry models")
    return errors


GOVERNANCE_FIELDS = (
    "allowed_training_purposes",
    "forbidden_feature_tags",
    "requires_privacy_review",
    "requires_bias_audit",
    "requires_model_card",
    "requires_dataset_card",
    "requires_training_manifest",
    "requires_human_review",
    "requires_dsr_invalidation",
    "production_promotion_allowed",
)


def check_model_governance() -> list[str]:
    """Every model must carry governance metadata; sensitive models must gate.

    - All model entries expose the full governance field set.
    - Sensitive (CRITICAL/HIGH) *trainable* models must require a model card and
      a training manifest, and must either require a privacy review or document
      a reason in ``governance_notes``.
    - Sensitive non-trainable (deterministic/composite) models are exempt from
      the training-artifact gates but must document their posture in
      ``governance_notes`` so the omission is auditable.
    """
    errors: list[str] = []
    sys.path.insert(0, str(ML_ROOT))
    try:
        from common.model_registry import (
            list_models,
            SensitivityTier,
            ImplementationType,
        )
    except ImportError as e:
        errors.append(f"Cannot import model_registry for governance check: {e}")
        return errors

    for entry in list_models():
        for field_name in GOVERNANCE_FIELDS:
            if not hasattr(entry, field_name):
                errors.append(
                    f"Model '{entry.model_id}' missing governance field '{field_name}'"
                )

        is_sensitive = entry.sensitivity_tier in (
            SensitivityTier.CRITICAL,
            SensitivityTier.HIGH,
        )
        if not is_sensitive:
            continue

        notes = (getattr(entry, "governance_notes", "") or "").strip()
        is_trainable = entry.implementation_type == ImplementationType.TRAINABLE_ML

        if is_trainable:
            if not entry.requires_model_card:
                errors.append(
                    f"Sensitive trainable model '{entry.model_id}' must set "
                    "requires_model_card=True"
                )
            if not entry.requires_training_manifest:
                errors.append(
                    f"Sensitive trainable model '{entry.model_id}' must set "
                    "requires_training_manifest=True"
                )
            if not entry.requires_privacy_review and not notes:
                errors.append(
                    f"Sensitive model '{entry.model_id}' must set "
                    "requires_privacy_review=True or document a reason in "
                    "governance_notes"
                )
        else:
            # Deterministic / composite sensitive models don't produce training
            # artifacts — but the omission must be documented.
            if not notes:
                errors.append(
                    f"Sensitive non-trainable model '{entry.model_id}' must "
                    "document its governance posture in governance_notes"
                )

    if not errors:
        ok("All models carry governance metadata; sensitive models satisfy governance gates")
    return errors


def check_no_privilege_header() -> list[str]:
    """Backend routes must not accept X-Batch-Privilege header as proof of privilege."""
    errors: list[str] = []
    routes_path = (
        REPO_ROOT
        / "Backend Architecture"
        / "aether-backend"
        / "services"
        / "ml_serving"
        / "routes.py"
    )
    if not routes_path.exists():
        return errors  # already checked above

    content = routes_path.read_text()
    stripped = re.sub(r"#.*$", "", content, flags=re.MULTILINE)
    stripped = re.sub(r'""".*?"""', "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)

    if "X-Batch-Privilege" in stripped:
        errors.append(
            "Backend routes check X-Batch-Privilege header for privilege. "
            "Remove this check — privilege must come from RBAC only."
        )
    else:
        ok("No X-Batch-Privilege header check in backend routes")
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

    print("\n--- Serving Endpoints ---")
    all_errors.extend(check_serving_endpoints())

    print("\n--- Backend Routes ---")
    all_errors.extend(check_backend_routes())

    print("\n--- Authored Duplicate Lists ---")
    all_errors.extend(check_no_authored_model_lists())

    print("\n--- ModelType Enum ---")
    all_errors.extend(check_model_type_enum())

    print("\n--- Model Governance ---")
    all_errors.extend(check_model_governance())

    print("\n--- Security: Privilege Header ---")
    all_errors.extend(check_no_privilege_header())

    print("\n" + "=" * 60)
    if all_errors:
        print(f"FAILED — {len(all_errors)} error(s):")
        for e in all_errors:
            print(f"  • {e}", file=sys.stderr)
        return 1

    print("PASSED — all ML registry checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
