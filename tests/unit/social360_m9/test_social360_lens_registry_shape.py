"""M9 registry-shape tests — SocialFi / EngagementFi / Narrative lenses.

Validates that the three M9 overlay lenses added to
``packages/shared/contracts/lens-registry.json`` and the ``social360`` surface
row added to ``packages/shared/contracts/surface-capability-registry.json`` are
internally consistent with the canonical filter-field registry
(``filter-field-registry.json``) and the projection-engine generator's expected
schema, so the integrator's eventual regeneration and parity gates pass.

These are pure-JSON tests: they load the canonical registry files only and never
depend on the generated twins, so they are equally valid before and after the
integrator regenerates.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "packages" / "shared" / "contracts"

_LENS = json.loads((CONTRACTS / "lens-registry.json").read_text(encoding="utf-8"))
_SURF = json.loads((CONTRACTS / "surface-capability-registry.json").read_text(encoding="utf-8"))
_FILTER = json.loads((CONTRACTS / "filter-field-registry.json").read_text(encoding="utf-8"))

_LOWER_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

# The three M9 overlay lenses.
M9_LENSES = ("socialfi", "engagementfi", "narrative")

# The generator's fixed schema field order for a lens entry (mirrors
# ``_LENS_FIELD_ORDER`` in scripts/generate_platform_contracts.py and the
# ``LensDescriptor`` TS interface) — a lens entry carries exactly these keys.
LENS_FIELD_ORDER = (
    "id", "displayName", "kind", "baseLens", "description", "domain",
    "applicableSubjectKinds", "temporalModes", "default",
)

# Filter-field categories each M9 lens surfaces (canonical expectation of this
# slice). Every category must exist in the filter-field registry, must have at
# least one registered field, and must be declared surface-capable on the
# social360 surface row.
M9_LENS_CATEGORIES: dict[str, frozenset[str]] = {
    "socialfi": frozenset({
        "social", "relationship", "incentive", "source", "evidence", "time", "entity",
    }),
    "engagementfi": frozenset({
        "social", "relationship", "incentive", "source", "evidence", "time", "entity",
    }),
    "narrative": frozenset({
        "narrative", "evidence", "source", "path", "social", "relationship", "time", "entity",
    }),
}

# The M1 filter-field categories the Social360 program added (fabric §84).
M1_SOCIAL_CATEGORIES = frozenset({
    "social", "relationship", "incentive", "source", "evidence", "path", "narrative",
})


def _lens_map() -> dict[str, dict]:
    return {lens["id"]: lens for lens in _LENS["lenses"]}


def _surface_map() -> dict[str, dict]:
    return {s["surfaceId"]: s for s in _SURF["surfaces"]}


def _field_categories() -> set[str]:
    return {f["category"] for f in _FILTER["fields"]}


# ── Lens registry shape ─────────────────────────────────────────────────────

def test_m9_lenses_present_as_overlays_on_standard():
    lenses = _lens_map()
    for lid in M9_LENSES:
        assert lid in lenses, f"expected lens {lid!r} in lens-registry.json"
        lens = lenses[lid]
        assert lens["kind"] == "overlay"
        assert lens["baseLens"] == "standard"
        assert lens["default"] is False
        assert lens["domain"] == lid


def test_m9_lens_schema_matches_generator_expected_shape():
    # The generator emits lens entries in a fixed field order and the TS twin
    # models exactly those fields; an extra key (e.g. a categories array) would
    # break the field-order frozenset match and the LensDescriptor interface.
    for lid in M9_LENSES:
        assert tuple(_lens_map()[lid].keys()) == LENS_FIELD_ORDER, lid


def test_lens_registry_passes_generator_validator():
    # The SAME validator the generator runs (scripts/lib/
    # intelligence_projection_validation.validate_lens_registry) must report no
    # errors for the registry that now carries the three M9 lenses.
    from scripts.lib.intelligence_projection_validation import validate_lens_registry

    errors = [
        v for v in validate_lens_registry(_LENS, {}) if v.severity == "error"
    ]
    assert errors == [], [e.message for e in errors]


def test_m9_lenses_apply_to_social360_projection_subjects():
    # The social360 projection row supports entity + relationship subjects; each
    # M9 lens must apply to those subjects so it composes over the projection
    # it overlays (CAPABILITY_MISSING would otherwise drop it at runtime).
    social360_subjects = frozenset(_social360_projection()["subjectKinds"])
    for lid in M9_LENSES:
        subject_kinds = frozenset(_lens_map()[lid]["applicableSubjectKinds"])
        assert social360_subjects <= subject_kinds, lid


def test_m9_lens_temporal_modes_within_social360_projection_modes():
    # The social360 projection supports window/as_of/relative; each M9 lens must
    # stay within those modes so it never requests a mode the projection cannot
    # honour (which would TEMPORAL_CONFLICT-degrade at runtime).
    social360_modes = frozenset(_social360_projection()["supportedTemporalModes"])
    for lid in M9_LENSES:
        modes = frozenset(_lens_map()[lid]["temporalModes"])
        assert modes <= social360_modes, lid


def _projections() -> dict[str, dict]:
    reg = json.loads((CONTRACTS / "intelligence-projection-registry.json").read_text(encoding="utf-8"))
    return {p["id"]: p for p in reg.get("projections", [])}


def _social360_projection() -> dict:
    projection = _projections().get("social360")
    assert projection is not None, "social360 projection row not found"
    return projection


# ── Surface-capability registry shape ───────────────────────────────────────

def test_social360_surface_row_declared_and_valid():
    surface = _surface_map().get("social360")
    assert surface is not None, "expected a 'social360' exploration-surface row"
    # Temporal modes / views must be a non-empty unique subset of the registry vocab.
    assert set(surface["supportedTemporalModes"]) <= set(_SURF["temporalModes"])
    assert set(surface["supportedViews"]) <= set(_SURF["views"])
    for key in (
        "supportsFacets", "supportsComparison", "supportsSelectionSets",
        "supportsSavedViews", "supportsExport",
    ):
        assert isinstance(surface[key], bool), key
    assert surface["supportedFieldCategories"]
    assert len(surface["supportedFieldCategories"]) == len(set(surface["supportedFieldCategories"]))


def test_social360_surface_categories_within_filter_registry():
    surface = _surface_map()["social360"]
    registered = set(_FILTER["categories"])
    assert set(surface["supportedFieldCategories"]) <= registered


def test_social360_surface_covers_m1_social_categories():
    surface = _surface_map()["social360"]
    declared = set(surface["supportedFieldCategories"])
    # The seven M1 social/relationship/evidence categories must all be declared
    # surface-capable so a social lens can honour their filters.
    assert M1_SOCIAL_CATEGORIES <= declared


def test_surface_capability_registry_passes_generator_validation():
    # Mirror of the generator's validate_surface_capabilities facts (the checks
    # that run before the twins are emitted), applied to every surface row so
    # the added social360 row cannot regress the rest of the registry.
    registered_categories = set(_FILTER["categories"])
    seen: set[str] = set()
    for surface in _SURF["surfaces"]:
        sid = surface["surfaceId"]
        assert _LOWER_SNAKE_RE.fullmatch(sid), f"surfaceId {sid!r} is not lower_snake"
        assert sid not in seen, f"duplicate surfaceId {sid!r}"
        seen.add(sid)
        for key, allowed in (
            ("supportedFieldCategories", registered_categories),
            ("supportedTemporalModes", set(_SURF["temporalModes"])),
            ("supportedViews", set(_SURF["views"])),
        ):
            values = surface[key]
            assert values, f"surface {sid!r} {key} must be non-empty"
            assert len(values) == len(set(values)), f"surface {sid!r} {key} has duplicates"
            assert set(values) <= allowed, f"surface {sid!r} {key} outside allowed vocab"


# ── Cross-registry consistency: lens categories <-> surface <-> filter fields ──

def test_every_m9_lens_category_is_registered_and_has_fields():
    field_categories = _field_categories()
    for lid, categories in M9_LENS_CATEGORIES.items():
        assert categories <= set(_FILTER["categories"]), lid
        assert categories <= field_categories, lid  # each category has >=1 field


def test_every_m9_lens_category_is_declared_surface_capable():
    declared = set(_surface_map()["social360"]["supportedFieldCategories"])
    for lid, categories in M9_LENS_CATEGORIES.items():
        assert categories <= declared, (
            f"lens {lid!r} surfaces categories not declared on the social360 surface row"
        )
