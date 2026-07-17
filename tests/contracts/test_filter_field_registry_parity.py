"""TS <-> Python parity for the filter-field registry.

`packages/shared/filter-fields.ts` and
`shared/exploration/generated_fields.py` are generated twins of
`packages/shared/contracts/filter-field-registry.json`. This test fails on
drift between the twins and the registry, if any field's operators escape the
canonical `FilterOperator` union in `packages/shared/graph-contract.ts`, if a
consent purpose is not registered in `consent-registry.json`, and if the TS
module leaves the barrel.
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

from shared.exploration.generated_fields import (  # noqa: E402
    FILTER_FIELD_CATEGORIES,
    FILTER_FIELD_DATA_TYPES,
    FILTER_FIELD_SENSITIVITIES,
    FILTER_FIELDS,
    FILTER_FIELDS_CONTRACT_VERSION,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "filter-fields.ts"
GRAPH_CONTRACT_TS = REPO_ROOT / "packages" / "shared" / "graph-contract.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "filter-field-registry.json"
CONSENT_REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in filter-fields.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _canonical_filter_operators() -> set[str]:
    text = GRAPH_CONTRACT_TS.read_text(encoding="utf-8")
    m = re.search(r"export type FilterOperator =(.*?)\n\n", text, re.S)
    assert m, "FilterOperator type not found in graph-contract.ts"
    operators = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert operators, "FilterOperator union parsed empty"
    return operators


def test_categories_parity():
    assert set(_const_array("filterFieldCategories")) == set(FILTER_FIELD_CATEGORIES)


def test_data_types_parity():
    assert set(_const_array("filterFieldDataTypes")) == set(FILTER_FIELD_DATA_TYPES)


def test_sensitivities_parity():
    assert set(_const_array("filterFieldSensitivities")) == set(FILTER_FIELD_SENSITIVITIES)


def test_field_ids_parity():
    ts_ids = set(re.findall(r"id: '([a-z0-9_.]+)'", TS_PATH.read_text(encoding="utf-8")))
    assert ts_ids == set(FILTER_FIELDS), (
        f"filter-field drift: TS-only={ts_ids - set(FILTER_FIELDS)}, "
        f"PY-only={set(FILTER_FIELDS) - ts_ids}"
    )


def test_operators_subset_of_graph_contract():
    """Every declared operator must live in the canonical FilterOperator union."""
    canonical = _canonical_filter_operators()
    for fid, field in FILTER_FIELDS.items():
        extra = set(field["operators"]) - canonical
        assert not extra, f"{fid} uses operators outside graph-contract FilterOperator: {extra}"
    # And the TS twin's inline operator arrays as well.
    ts_text = TS_PATH.read_text(encoding="utf-8")
    for ops in re.findall(r"operators: \[(.*?)\]", ts_text):
        assert set(re.findall(r"'([a-z_]+)'", ops)) <= canonical


def test_consent_purposes_registered():
    purposes = {
        p["key"]
        for p in json.loads(CONSENT_REGISTRY_PATH.read_text(encoding="utf-8"))["purposes"]
    }
    for fid, field in FILTER_FIELDS.items():
        if "consent_purpose" in field:
            assert field["consent_purpose"] in purposes, (
                f"{fid} names unregistered consent purpose {field['consent_purpose']!r}"
            )


def test_field_prefix_matches_category():
    for fid, field in FILTER_FIELDS.items():
        assert fid.split(".", 1)[0] == field["category"], fid
        assert field["category"] in FILTER_FIELD_CATEGORIES
        assert field["data_type"] in FILTER_FIELD_DATA_TYPES
        assert field["sensitivity"] in FILTER_FIELD_SENSITIVITIES


def test_generated_fields_match_registry():
    """Generated Python fields mirror the JSON registry (regen if this fails)."""
    registry = _registry()
    assert FILTER_FIELDS_CONTRACT_VERSION == registry["contractVersion"]
    assert list(FILTER_FIELD_CATEGORIES) == registry["categories"]
    assert list(FILTER_FIELD_DATA_TYPES) == registry["dataTypes"]
    assert list(FILTER_FIELD_SENSITIVITIES) == registry["sensitivities"]
    expected = {}
    for field in registry["fields"]:
        entry = {
            "label": field["label"],
            "category": field["category"],
            "data_type": field["dataType"],
            "operators": tuple(field["operators"]),
            "sensitivity": field["sensitivity"],
        }
        if "consentPurpose" in field:
            entry["consent_purpose"] = field["consentPurpose"]
        if "minimumCohortSize" in field:
            entry["minimum_cohort_size"] = field["minimumCohortSize"]
        expected[field["id"]] = entry
    assert FILTER_FIELDS == expected


def test_city_field_has_cohort_floor():
    """geography.city must keep its k-anonymity floor."""
    city = FILTER_FIELDS["geography.city"]
    assert city["minimum_cohort_size"] == 25
    assert city["sensitivity"] == "tenant_internal"


def test_barrel_exports_filter_fields():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './filter-fields';" in index
