"""Schema contract test: NoesisResponse Pydantic schema must not regress silently.

If a field is renamed, removed, or its type changes, this test fails CI before
the frontend's Zod schema silently diverges.

To update the baseline after an intentional schema change:
    cd "Backend Architecture/aether-backend"
    python -c "
import json
from services.noesis.models import NoesisResponse
print(json.dumps(NoesisResponse.model_json_schema(), indent=2, sort_keys=True))
" > tests/contracts/noesis_response_contract.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.noesis.models import NoesisResponse

_BASELINE_PATH = Path(__file__).parent / "noesis_response_contract.json"

# Required top-level response fields that the frontend Zod schema depends on.
_REQUIRED_FIELDS = {
    "answer",
    "mode",
    "intent",
    "confidence",
    "entities",
    "results",
    "graph",
    "actions",
    "warnings",
    "evidence",
}


def test_schema_required_fields_present():
    """All frontend-critical fields must exist in the Pydantic schema."""
    schema = NoesisResponse.model_json_schema()
    props = set(schema.get("properties", {}).keys())
    missing = _REQUIRED_FIELDS - props
    assert not missing, f"Missing required response fields: {missing}"


def test_schema_matches_baseline():
    """Generated schema must exactly match the checked-in contract baseline.

    If this fails after an intentional change, regenerate:
        python -c "import json; from services.noesis.models import NoesisResponse;
        print(json.dumps(NoesisResponse.model_json_schema(), indent=2, sort_keys=True))"
        > tests/contracts/noesis_response_contract.json
    """
    assert _BASELINE_PATH.exists(), f"Baseline not found at {_BASELINE_PATH}"
    baseline = json.loads(_BASELINE_PATH.read_text())
    current = json.loads(
        json.dumps(NoesisResponse.model_json_schema(), sort_keys=True)
    )
    assert current == baseline, (
        "NoesisResponse schema has drifted from the baseline contract. "
        "If this is intentional, regenerate tests/contracts/noesis_response_contract.json "
        "and update the frontend Zod schema accordingly."
    )


def test_evidence_envelope_in_schema():
    """EvidenceEnvelope must appear as a $def in the schema."""
    schema = NoesisResponse.model_json_schema()
    defs = schema.get("$defs", {})
    assert "EvidenceEnvelope" in defs, "EvidenceEnvelope not found in schema $defs"
    env_props = set(defs["EvidenceEnvelope"].get("properties", {}).keys())
    assert {"sources", "claims", "sufficient"}.issubset(env_props), (
        f"EvidenceEnvelope missing expected fields; found: {env_props}"
    )


def test_noesis_action_types_stable():
    """NoesisAction type enum must not change without updating frontend."""
    schema = NoesisResponse.model_json_schema()
    action_def = schema.get("$defs", {}).get("NoesisAction", {})
    type_prop = action_def.get("properties", {}).get("type", {})
    enum_values = set(type_prop.get("enum", []))
    expected = {"navigate", "open_inspector", "highlight_graph", "refine_query"}
    assert enum_values == expected, f"NoesisAction type enum changed: {enum_values}"
