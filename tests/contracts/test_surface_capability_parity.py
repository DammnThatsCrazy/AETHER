"""TS <-> Python parity for the surface-capability registry.

`packages/shared/surface-capabilities.ts` and
`shared/exploration/generated_surfaces.py` are generated twins of
`packages/shared/contracts/surface-capability-registry.json`. This test fails
on drift between the twins and the registry, if a surface claims a
field category outside the filter-field registry or a temporal mode / view
outside the declared sets, and if the TS module leaves the barrel.
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

from shared.exploration.generated_fields import FILTER_FIELD_CATEGORIES  # noqa: E402
from shared.exploration.generated_surfaces import (  # noqa: E402
    EXPLORATION_SURFACE_IDS,
    EXPLORATION_TEMPORAL_MODES,
    EXPLORATION_VIEWS,
    FILTER_DISPOSITIONS,
    SURFACE_CAPABILITIES,
    SURFACE_CAPABILITIES_CONTRACT_VERSION,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "surface-capabilities.ts"
# The disposition/view/mode vocabularies are OWNED by exploration-contract.ts;
# the generated surface module imports their types instead of re-declaring the
# consts, so vocabulary parity is asserted against the owner file.
EXPLORATION_CONTRACT_TS = REPO_ROOT / "packages" / "shared" / "exploration-contract.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "surface-capability-registry.json"

_EXPECTED_SURFACES = {
    "graph",
    "profile360",
    "campaign360",
    "cluster360",
    "geo",
    "journeys",
    "timeline",
    "product_intelligence",
    "temporal_observatory",
    "comparison_workbench",
    "outcome360",
    "economic360",
    "connection360",
    "infrastructure360",
    "temporal360",
    "population360",
    "geographic360",
}


def _const_array(name: str, path=None) -> list[str]:
    text = (path or TS_PATH).read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in surface-capabilities.ts"
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def test_surface_ids_parity():
    assert set(_const_array("explorationSurfaceIds")) == set(EXPLORATION_SURFACE_IDS)
    assert set(EXPLORATION_SURFACE_IDS) == _EXPECTED_SURFACES


def test_temporal_modes_parity():
    assert set(_const_array("explorationTemporalModes", EXPLORATION_CONTRACT_TS)) == set(EXPLORATION_TEMPORAL_MODES)
    assert set(EXPLORATION_TEMPORAL_MODES) == {"window", "as_of", "compare", "relative"}


def test_views_parity():
    assert set(_const_array("explorationViews", EXPLORATION_CONTRACT_TS)) == set(EXPLORATION_VIEWS)
    assert set(EXPLORATION_VIEWS) == {"graph", "table", "map", "timeline", "flow", "comparison"}


def test_filter_dispositions_parity():
    assert set(_const_array("filterDispositions", EXPLORATION_CONTRACT_TS)) == set(FILTER_DISPOSITIONS)
    assert set(FILTER_DISPOSITIONS) == {
        "applied", "translated", "unsupported", "suppressed", "not_applicable",
    }


def test_surface_constraints():
    """Every surface's declarations stay inside the canonical vocabularies."""
    for sid, surface in SURFACE_CAPABILITIES.items():
        assert set(surface["supported_field_categories"]) <= set(FILTER_FIELD_CATEGORIES), sid
        assert set(surface["supported_temporal_modes"]) <= set(EXPLORATION_TEMPORAL_MODES), sid
        assert set(surface["supported_views"]) <= set(EXPLORATION_VIEWS), sid
        for flag in (
            "supports_facets",
            "supports_comparison",
            "supports_selection_sets",
            "supports_saved_views",
            "supports_export",
        ):
            assert isinstance(surface[flag], bool), f"{sid}.{flag}"


def test_generated_surfaces_match_registry():
    """Generated Python surfaces mirror the JSON registry (regen if this fails)."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert SURFACE_CAPABILITIES_CONTRACT_VERSION == registry["contractVersion"]
    assert list(EXPLORATION_TEMPORAL_MODES) == registry["temporalModes"]
    assert list(EXPLORATION_VIEWS) == registry["views"]
    assert list(FILTER_DISPOSITIONS) == registry["filterDispositions"]
    expected = {}
    for surface in registry["surfaces"]:
        expected[surface["surfaceId"]] = {
            "supported_field_categories": tuple(surface["supportedFieldCategories"]),
            "supported_temporal_modes": tuple(surface["supportedTemporalModes"]),
            "supported_views": tuple(surface["supportedViews"]),
            "supports_facets": surface["supportsFacets"],
            "supports_comparison": surface["supportsComparison"],
            "supports_selection_sets": surface["supportsSelectionSets"],
            "supports_saved_views": surface["supportsSavedViews"],
            "supports_export": surface["supportsExport"],
        }
    assert SURFACE_CAPABILITIES == expected
    assert list(EXPLORATION_SURFACE_IDS) == sorted(expected)


def test_ts_surface_map_covers_all_surfaces():
    text = TS_PATH.read_text(encoding="utf-8")
    mapped = set(re.findall(r"surfaceId: '([a-z0-9_]+)'", text))
    assert mapped == set(EXPLORATION_SURFACE_IDS)


def test_barrel_exports_surface_capabilities():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './surface-capabilities';" in index
