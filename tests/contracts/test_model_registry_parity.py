"""TS <-> Python parity for the multi-model harness registry.

`packages/shared/model-registry.ts` and
`shared/model_governance/generated_model_registry.py` are generated twins of
`packages/shared/contracts/model-registry.json`. This test fails on drift in the
version, vocabulary arrays, aliases, model catalog (13 canonical keys per model,
per-index scalar/nested parity), duplicate/invalid modelIds, and if the TS
module is not exported from the barrel.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.model_governance.generated_model_registry import (  # noqa: E402
    MODEL_REGISTRY_ALIASES,
    MODEL_REGISTRY_CAPABILITIES,
    MODEL_REGISTRY_EFFORT_LEVELS,
    MODEL_REGISTRY_MODEL_STATUSES,
    MODEL_REGISTRY_MODELS,
    MODEL_REGISTRY_PROVIDERS,
    MODEL_REGISTRY_THINKING_MODES,
    MODEL_REGISTRY_VERSION,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "model-registry.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "model-registry.json"

_MODEL_KEYS = frozenset(
    {
        "modelId",
        "provider",
        "family",
        "contextWindowTokens",
        "maxOutputTokens",
        "capabilities",
        "thinkingModes",
        "effortLevels",
        "samplingParamsSupported",
        "inputCostPerMTok",
        "outputCostPerMTok",
        "status",
        "notes",
    }
)

def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in model-registry.ts"
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def _const_version() -> str:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"modelRegistryVersion\s*=\s*'([^']+)'", text)
    assert m, "modelRegistryVersion not found in model-registry.ts"
    return m.group(1)


def _alias_map() -> dict[str, str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"modelRegistryAliases[^\{]*\{(.*?)\}\s*;", text, re.S)
    assert m, "modelRegistryAliases object not found in model-registry.ts"
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", m.group(1)))


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _model_objects() -> list[str]:
    """Each TS `{...}` model literal from the `modelRegistryModels` block."""
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"modelRegistryModels[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, "modelRegistryModels block not found in model-registry.ts"
    return re.findall(r"\{[^{}]*\}", m.group(1), re.S)


def _field(obj: str, field: str, pattern: str) -> str:
    m = re.search(rf"{field}:\s*({pattern})", obj, re.S)
    assert m, f"field {field!r} not found in TS model object"
    # The outer `({pattern})` wrapping group plus any captures inside the
    # pattern means the innermost group holds the actual value (e.g. for the
    # `'([^']+)'` string pattern it is the unquoted text).
    return m.groups()[-1]


def _parse_model_object(obj: str) -> dict:
    def _str(field: str) -> str:
        return _field(obj, field, r"'([^']+)'")

    def _int(field: str) -> int:
        return int(_field(obj, field, r"(\d+)"))

    def _bool(field: str) -> bool:
        return _field(obj, field, r"(true|false)") == "true"

    def _float(field: str) -> float:
        return float(_field(obj, field, r"([0-9.]+)"))

    def _arr(field: str) -> tuple[str, ...]:
        inner = _field(obj, field, r"\[(.*?)\]")
        return tuple(re.findall(r"'([a-z0-9_]+)'", inner))

    return {
        "modelId": _str("modelId"),
        "provider": _str("provider"),
        "family": _str("family"),
        "contextWindowTokens": _int("contextWindowTokens"),
        "maxOutputTokens": _int("maxOutputTokens"),
        "capabilities": _arr("capabilities"),
        "thinkingModes": _arr("thinkingModes"),
        "effortLevels": _arr("effortLevels"),
        "samplingParamsSupported": _bool("samplingParamsSupported"),
        "inputCostPerMTok": _float("inputCostPerMTok"),
        "outputCostPerMTok": _float("outputCostPerMTok"),
        "status": _str("status"),
        "notes": _str("notes"),
    }


def _json_models() -> dict[str, dict]:
    """Canonical projection of the JSON `models` array keyed by modelId."""
    projection = {}
    for model in _registry()["models"]:
        entry = dict(model)
        for key in ("capabilities", "thinkingModes", "effortLevels"):
            entry[key] = tuple(model[key])
        projection[model["modelId"]] = entry
    return projection


def test_model_registry_version_parity():
    assert _const_version() == MODEL_REGISTRY_VERSION
    assert MODEL_REGISTRY_VERSION == _registry()["contractVersion"]


def test_providers_parity():
    assert set(_const_array("modelRegistryProviders")) == set(MODEL_REGISTRY_PROVIDERS)
    assert _registry()["providers"] == list(MODEL_REGISTRY_PROVIDERS)


def test_capabilities_parity():
    assert set(_const_array("modelRegistryCapabilities")) == set(MODEL_REGISTRY_CAPABILITIES)
    assert _registry()["capabilities"] == list(MODEL_REGISTRY_CAPABILITIES)


def test_thinking_modes_parity():
    assert set(_const_array("modelRegistryThinkingModes")) == set(MODEL_REGISTRY_THINKING_MODES)
    assert _registry()["thinkingModes"] == list(MODEL_REGISTRY_THINKING_MODES)


def test_effort_levels_parity():
    assert set(_const_array("modelRegistryEffortLevels")) == set(MODEL_REGISTRY_EFFORT_LEVELS)
    assert _registry()["effortLevels"] == list(MODEL_REGISTRY_EFFORT_LEVELS)


def test_model_statuses_parity():
    assert set(_const_array("modelRegistryModelStatuses")) == set(MODEL_REGISTRY_MODEL_STATUSES)
    assert _registry()["modelStatuses"] == list(MODEL_REGISTRY_MODEL_STATUSES)


def test_aliases_parity():
    assert _alias_map() == dict(MODEL_REGISTRY_ALIASES)
    assert dict(MODEL_REGISTRY_ALIASES) == _registry()["aliases"]


def test_models_count():
    assert len(MODEL_REGISTRY_MODELS) == 10
    assert len(_model_objects()) == 10


def test_model_fields_parity():
    """Per-index: TS object literal matches the PY dict on all 13 fields."""
    ts_objects = _model_objects()
    assert len(ts_objects) == len(MODEL_REGISTRY_MODELS)
    for i, obj in enumerate(ts_objects):
        ts_keys = set(re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*):", obj, re.M))
        py_keys = set(MODEL_REGISTRY_MODELS[i].keys())
        assert ts_keys == _MODEL_KEYS, (
            f"model[{i}] TS key drift: TS-only={ts_keys - _MODEL_KEYS}, "
            f"missing={_MODEL_KEYS - ts_keys}"
        )
        assert py_keys == _MODEL_KEYS, (
            f"model[{i}] PY key drift: PY-only={py_keys - _MODEL_KEYS}, "
            f"missing={_MODEL_KEYS - py_keys}"
        )
        parsed = _parse_model_object(obj)
        for key in _MODEL_KEYS:
            assert parsed[key] == MODEL_REGISTRY_MODELS[i][key], (
                f"model[{i}].{key} drift: TS={parsed[key]!r} PY={MODEL_REGISTRY_MODELS[i][key]!r}"
            )


def test_generated_models_match_registry():
    """Generated Python catalog mirrors the JSON registry (regen if this fails)."""
    py_by_id = {m["modelId"]: dict(m) for m in MODEL_REGISTRY_MODELS}
    assert py_by_id == _json_models()
    model_ids = set(py_by_id)
    # Alias keys are operator-facing shorthands; each must resolve (through the
    # alias map) to a canonical modelId registered in the catalog.
    assert all(value in model_ids for value in MODEL_REGISTRY_ALIASES.values())


def test_model_ids_unique_and_valid():
    ids = [m["modelId"] for m in MODEL_REGISTRY_MODELS]
    assert len(ids) == len(set(ids)), "duplicate modelId in MODEL_REGISTRY_MODELS"
    assert all(isinstance(i, str) and i for i in ids), "modelId must be a non-empty string"
    assert set(MODEL_REGISTRY_ALIASES.values()) <= set(ids), "alias value is not a modelId"


def test_barrel_exports_model_registry():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './model-registry';" in index
