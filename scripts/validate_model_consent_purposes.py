#!/usr/bin/env python3
"""Validate ML model/feature purpose declarations against the consent registry.

Canonical source of truth: ``packages/shared/contracts/consent-registry.json``.

Every ML model in ``ML Models/aether-ml/common/model_registry.py`` must declare
non-empty ``allowed_training_purposes`` (training-data scope) and
``required_inference_purposes`` (serving scope), and every declared purpose —
including each feature contract's ``required_purposes`` in
``ML Models/aether-ml/common/feature_contracts.py`` — must be a canonical
registry key. Purpose governance is fail-closed: a model with no declared
purposes, or one referencing an unknown purpose, must never ship.

Exits 0 on success, 1 with one line per violation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ML_ROOT = ROOT / "ML Models" / "aether-ml"
REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"


def load_registry_keys() -> frozenset[str]:
    """Canonical consent purpose keys from the registry."""
    data = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
    return frozenset(p["key"] for p in data["purposes"])


def collect_errors(models, contracts, registry_keys) -> list[str]:
    """Pure validation core (also exercised in-process by the ML test suite).

    Args:
        models: iterable of ModelEntry-like objects.
        contracts: iterable of FeatureContract-like objects.
        registry_keys: set of canonical consent purpose keys.
    """
    errors: list[str] = []

    for entry in models:
        for field_name in ("allowed_training_purposes", "required_inference_purposes"):
            purposes = getattr(entry, field_name)
            if not purposes:
                errors.append(
                    f"model '{entry.model_id}': {field_name} is empty — every "
                    "model must declare a non-empty purpose scope (fail closed)"
                )
                continue
            for key in purposes:
                if key not in registry_keys:
                    errors.append(
                        f"model '{entry.model_id}': {field_name} references "
                        f"unknown consent purpose '{key}'"
                    )

    for contract in contracts:
        purposes = contract.required_purposes
        if not purposes:
            errors.append(
                f"feature contract '{contract.contract_id}' (model "
                f"'{contract.model_id}'): required_purposes is empty — every "
                "contract must declare a non-empty purpose scope (fail closed)"
            )
            continue
        for key in purposes:
            if key not in registry_keys:
                errors.append(
                    f"feature contract '{contract.contract_id}' (model "
                    f"'{contract.model_id}'): required_purposes references "
                    f"unknown consent purpose '{key}'"
                )

    return errors


def main() -> int:
    sys.path.insert(0, str(ML_ROOT))
    from common.feature_contracts import list_feature_contracts
    from common.model_registry import list_models

    registry_keys = load_registry_keys()
    errors = collect_errors(list_models(), list_feature_contracts(), registry_keys)

    if errors:
        print("model consent-purpose validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    n_models = len(list_models())
    n_contracts = len(list_feature_contracts())
    print(
        f"model consent-purpose validation OK: {n_models} models and "
        f"{n_contracts} feature contracts reference only the "
        f"{len(registry_keys)} canonical consent purposes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
