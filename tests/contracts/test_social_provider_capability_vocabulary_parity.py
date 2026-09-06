"""TS <-> Python parity for the UPR social provider capability vocabulary.

`packages/shared/social-provider-capability-vocabulary.ts` and
`shared/social_provider/generated_social_provider_capability_vocabulary.py` are
generated twins of
`packages/shared/contracts/social-provider-capability-vocabulary.json`. This
test fails on drift in the schema/contract versions, the canonical description
and grammar, every vocabulary array (capabilities, acquisition classes,
lifecycle states, empty-success-forbidden states), the example identities, the
prose rules, the barrel export, and the repo-doctor unified-platform clean list.
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

from shared.social_provider.generated_social_provider_capability_vocabulary import (  # noqa: E402
    SOCIAL_PROVIDER_ACQUISITION_CLASSES,
    SOCIAL_PROVIDER_CAPABILITIES,
    SOCIAL_PROVIDER_CAPABILITY_GRAMMAR,
    SOCIAL_PROVIDER_CAPABILITY_RULES,
    SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_CONTRACT_VERSION,
    SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_DESCRIPTION,
    SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_SCHEMA_VERSION,
    SOCIAL_PROVIDER_EMPTY_SUCCESS_FORBIDDEN_STATES,
    SOCIAL_PROVIDER_EXAMPLE_CAPABILITIES,
    SOCIAL_PROVIDER_LIFECYCLE_STATES,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "social-provider-capability-vocabulary.ts"
JSON_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "social-provider-capability-vocabulary.json"
INDEX_PATH = REPO_ROOT / "packages" / "shared" / "index.ts"
REPO_DOCTOR_PATH = REPO_ROOT / "scripts" / "repo_doctor.py"

# json key -> (TS const array name, Python constant)
_TS_NAME = {
    "capabilities": "socialProviderCapabilities",
    "acquisitionClasses": "socialProviderAcquisitionClasses",
    "lifecycleStates": "socialProviderLifecycleStates",
    "emptySuccessForbiddenStates": "socialProviderEmptySuccessForbiddenStates",
    "exampleCapabilities": "socialProviderExampleCapabilities",
    "rules": "socialProviderCapabilityRules",
}
_PY_VALUE = {
    "capabilities": SOCIAL_PROVIDER_CAPABILITIES,
    "acquisitionClasses": SOCIAL_PROVIDER_ACQUISITION_CLASSES,
    "lifecycleStates": SOCIAL_PROVIDER_LIFECYCLE_STATES,
    "emptySuccessForbiddenStates": SOCIAL_PROVIDER_EMPTY_SUCCESS_FORBIDDEN_STATES,
    "exampleCapabilities": SOCIAL_PROVIDER_EXAMPLE_CAPABILITIES,
    "rules": SOCIAL_PROVIDER_CAPABILITY_RULES,
}

# json key -> (TS scalar const name, Python scalar constant)
_SCALARS = {
    "schemaVersion": ("socialProviderCapabilityVocabularySchemaVersion", SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_SCHEMA_VERSION),
    "contractVersion": ("socialProviderCapabilityVocabularyContractVersion", SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_CONTRACT_VERSION),
    "description": ("socialProviderCapabilityVocabularyDescription", SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_DESCRIPTION),
    "capabilityGrammar": ("socialProviderCapabilityGrammar", SOCIAL_PROVIDER_CAPABILITY_GRAMMAR),
}


def _ts_text() -> str:
    return TS_PATH.read_text(encoding="utf-8")


def _ts_scalar(name: str) -> str:
    text = _ts_text()
    m = re.search(rf"{name}\s*=\s*'((?:[^'\\]|\\.)*)'\s*as const;", text, re.S)
    assert m, f"scalar const {name!r} not found in social-provider-capability-vocabulary.ts"
    raw = m.group(1)
    return raw.replace("\\'", "'").replace("\\\\", "\\")


def _ts_array(name: str) -> list[str]:
    text = _ts_text()
    m = re.search(rf"{name}\s*=\s*\[(.*?)\]\s*as const;", text, re.S)
    assert m, f"const array {name!r} not found in social-provider-capability-vocabulary.ts"
    body = m.group(1)
    values = re.findall(r"'((?:[^'\\]|\\.)*)'", body)
    return [v.replace("\\'", "'").replace("\\\\", "\\") for v in values]


def _json() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_social_vocabulary_scalar_parity():
    registry = _json()
    for key, (ts_name, py_value) in _SCALARS.items():
        ts_value = _ts_scalar(ts_name)
        assert py_value == registry[key], f"PY {key!r} drifts from JSON"
        assert ts_value == registry[key], f"TS {key!r} drifts from JSON"
        assert ts_value == py_value


def test_social_vocabulary_array_parity():
    registry = _json()
    for key, py_value in _PY_VALUE.items():
        ts_name = _TS_NAME[key]
        ts_value = _ts_array(ts_name)
        assert list(py_value) == registry[key], f"PY vocab {key!r} drifts from JSON"
        assert ts_value == registry[key], f"TS vocab {key!r} drifts from JSON"
        assert set(ts_value) == set(py_value), f"TS/PY vocab {key!r} disagree"


def test_social_vocabulary_canonical_sets():
    """Invariant grounding used by the runtime gate: the capability grammar is
    family.product.capability, product == social in the examples, and the
    capabilities/acquisition/lifecycle sets are the closed canonical lists."""
    registry = _json()
    assert registry["capabilityGrammar"] == "family.product.capability"
    for example in registry["exampleCapabilities"]:
        parts = example.split(".")
        assert len(parts) == 3
        assert parts[1] == "social"
        assert parts[2] in registry["capabilities"]
    assert "credential_waiting" in registry["lifecycleStates"]
    assert "credential_waiting" in registry["emptySuccessForbiddenStates"]


def test_social_vocabulary_rules_are_stable_ordered():
    """Rules and example identities are emitted in JSON file order (no sorting
    surprise) and stay unique."""
    registry = _json()
    rules = list(_PY_VALUE["rules"])
    assert rules == registry["rules"]
    assert len(rules) == len(set(rules))
    examples = list(_PY_VALUE["exampleCapabilities"])
    assert examples == registry["exampleCapabilities"]
    assert len(examples) == len(set(examples))


def test_barrel_exports_social_provider_capability_vocabulary():
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert "export * from './social-provider-capability-vocabulary';" in index


def test_repo_doctor_clean_list_covers_social_twins():
    text = REPO_DOCTOR_PATH.read_text(encoding="utf-8")
    assert "packages/shared/social-provider-capability-vocabulary.ts" in text
    assert (
        "Backend Architecture/aether-backend/shared/social_provider/"
        "generated_social_provider_capability_vocabulary.py" in text
    )
