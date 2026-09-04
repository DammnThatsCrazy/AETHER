"""Intelligence Projection Registry schema tests (P0.2, group 1).

Loads the REAL ``packages/shared/contracts/intelligence-projection-registry.json``
and asserts the structural invariants the validation core enforces: 19
projections, unique lower_snake ids, every required per-entry field present,
``ownsCanonicalTruth is False`` for all, exactly the seven 360 vertical slices
``implemented`` (outcome360 / economic360 / infrastructure360 / communication360 /
temporal360 / population360 / geographic360) with the rest ``in_flight``,
consistent vocab enums, well-formed pending declarations,
canonical authorities within AUTHORITY_INDEX, hard dependencies within
SPINE_INDEX or declared pending, and well-formed projection-plane capability
keys. Finally asserts ``validate_registry_schema`` agrees with all of the above
by returning an empty violation list for the real registry.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.intelligence_projection_validation import (  # noqa: E402
    AUTHORITY_INDEX,
    PROJECTION_CAPABILITY_VERBS,
    SPINE_INDEX,
    validate_dependency_dag,
    validate_registry_schema,
)

_REGISTRY_JSON = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"
)

_EXPECTED_IDS = frozenset(
    {
        "profile360",
        "agent360",
        "relationship360",
        "social360",
        "episode360",
        "communication360",
        "execution360",
        "temporal360",
        "geographic360",
        "population360",
        "cluster360",
        "outcome360",
        "economic360",
        "campaign360",
        "risk360",
        "fraud360",
        "source360",
        "connection360",
        "infrastructure360",
    }
)

_REQUIRED_FIELDS = frozenset(
    {
        "id",
        "displayName",
        "projectionKind",
        "implementationState",
        "implementationBlueprint",
        "ownsCanonicalTruth",
        "subjectKinds",
        "canonicalAuthorities",
        "hardDependencies",
        "projectionDependencies",
        "optionalProjectionDependencies",
        "inputRefs",
        "outputSections",
        "supportedTemporalModes",
        "surfaceIds",
        "capabilityKeys",
        "metricRefs",
        "graphMutationPolicy",
        "requiresEvidence",
        "requiresDimensionState",
        "requiresFreshness",
        "requiresLimitations",
        "tenantScoped",
        "policyScoped",
        "readinessRequirements",
        "security",
        "costProfile",
        "commercialClassification",
        "legacyBindings",
        "deprecatedReason",
        "successorId",
        "pendingAuthority",
        "pendingReference",
    }
)

_PENDING_KEYS = frozenset({"id", "kind", "reason", "resolvesInProjection"})

_LOWER_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _registry() -> dict:
    return json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))


def _projections() -> list[dict]:
    return _registry()["projections"]


def _mk_reg(entries: list[dict]) -> dict:
    """Minimal in-memory registry with the vocab arrays the schema gate needs."""
    return {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "projectionKinds": ["profile_360", "measurement_360", "risk_360"],
        "implementationStates": ["registered", "in_flight", "implemented", "deprecated"],
        "graphMutationPolicies": ["read_only", "canonical_gateway_only"],
        "sectionStates": ["live", "deprecated", "provisioned"],
        "temporalModes": ["window", "as_of", "compare", "relative"],
        "migrationModes": ["adapter", "converged", "none"],
        "subjectKinds": ["person", "company", "campaign", "measurement"],
        "projections": entries,
    }


def _entry(pid: str, **overrides: object) -> dict:
    """A fully-populated per-entry fixture; override only the field under test."""
    base = {
        "id": pid,
        "displayName": pid,
        "projectionKind": "profile_360",
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/aether-x.md",
        "ownsCanonicalTruth": False,
        "subjectKinds": ["person"],
        "canonicalAuthorities": [],
        "hardDependencies": [],
        "projectionDependencies": [],
        "optionalProjectionDependencies": [],
        "inputRefs": [],
        "outputSections": [],
        "supportedTemporalModes": ["window"],
        "surfaceIds": ["surface_evolve"],
        "capabilityKeys": [],
        "metricRefs": [],
        "graphMutationPolicy": "read_only",
        "requiresEvidence": False,
        "requiresDimensionState": False,
        "requiresFreshness": False,
        "requiresLimitations": False,
        "tenantScoped": True,
        "policyScoped": True,
        "readinessRequirements": {},
        "security": {},
        "costProfile": {},
        "commercialClassification": {},
        "legacyBindings": {"migrationMode": "adapter"},
        "deprecatedReason": None,
        "successorId": None,
        "pendingAuthority": [],
        "pendingReference": [],
    }
    base.update(overrides)
    return base


def test_registry_has_19_projections() -> None:
    projections = _projections()
    assert len(projections) == 19
    assert {p["id"] for p in projections} == _EXPECTED_IDS


def test_projection_ids_unique_and_lower_snake() -> None:
    projections = _projections()
    ids = [p["id"] for p in projections]
    assert len(ids) == len(set(ids))
    for pid in ids:
        assert _LOWER_SNAKE_RE.fullmatch(pid), f"id {pid!r} is not lower_snake"


def test_every_required_field_present() -> None:
    for p in _projections():
        for field in _REQUIRED_FIELDS:
            assert field in p, f"{p['id']}: missing required field {field!r}"


def test_owns_canonical_truth_false_for_all() -> None:
    for p in _projections():
        assert p["ownsCanonicalTruth"] is False, (
            f"{p['id']}: ownsCanonicalTruth must be structurally False"
        )


def test_implementation_states_match_slice_program() -> None:
    # Exactly the seven 360 vertical slices are implemented; everything else
    # stays in_flight. No registered/deprecated rows, and the implemented set is
    # honest (each has zero pending + converged bindings — proven by the
    # dependency-DAG gate in the order-resilience suite).
    states = {p["implementationState"] for p in _projections()}
    assert states == {"in_flight", "implemented"}
    implemented = {
        p["id"] for p in _projections() if p["implementationState"] == "implemented"
    }
    assert implemented == {
        "outcome360",
        "economic360",
        "infrastructure360",
        "communication360",
        "temporal360",
        "population360",
        "geographic360",
    }
    assert all(
        p["implementationState"] == "in_flight"
        for p in _projections()
        if p["id"] not in implemented
    )


def test_vocab_enums_consistent() -> None:
    reg = _registry()
    projections = _projections()
    kinds = set(reg["projectionKinds"])
    states = set(reg["implementationStates"])
    policies = set(reg["graphMutationPolicies"])
    migration_modes = set(reg["migrationModes"])
    subject_kinds = set(reg["subjectKinds"])
    temporal_modes = set(reg["temporalModes"])

    for p in projections:
        assert p["projectionKind"] in kinds, f"{p['id']}: kind {p['projectionKind']!r} not in projectionKinds"
        assert p["implementationState"] in states, f"{p['id']}: state {p['implementationState']!r} not in implementationStates"
        assert p["graphMutationPolicy"] in policies, f"{p['id']}: policy {p['graphMutationPolicy']!r} not in graphMutationPolicies"
        assert p["legacyBindings"]["migrationMode"] in migration_modes, (
            f"{p['id']}: migrationMode {p['legacyBindings']['migrationMode']!r} not in migrationModes"
        )
        for kind in p["subjectKinds"]:
            assert kind in subject_kinds, f"{p['id']}: subjectKind {kind!r} not in subjectKinds"
        for mode in p["supportedTemporalModes"]:
            assert mode in temporal_modes, f"{p['id']}: temporalMode {mode!r} not in temporalModes"


def test_pending_entries_well_formed() -> None:
    for p in _projections():
        for decl in list(p.get("pendingAuthority", [])) + list(p.get("pendingReference", [])):
            assert set(decl) == _PENDING_KEYS, (
                f"{p['id']}: pending declaration {decl!r} must have exactly "
                "{id, kind, reason, resolvesInProjection}"
            )
            assert decl["resolvesInProjection"] == p["id"], (
                f"{p['id']}: pending {decl['id']!r} resolvesInProjection must be the declaring projection"
            )


def test_canonical_authorities_in_index() -> None:
    for p in _projections():
        for authority in p["canonicalAuthorities"]:
            assert authority in AUTHORITY_INDEX, (
                f"{p['id']}: canonical authority {authority!r} not in AUTHORITY_INDEX"
            )


def test_hard_dependencies_resolve() -> None:
    for p in _projections():
        declared = {d["id"] for d in p.get("pendingAuthority", [])}
        for spine in p["hardDependencies"]:
            assert spine in SPINE_INDEX or spine in declared, (
                f"{p['id']}: hardDependency {spine!r} neither in SPINE_INDEX nor declared pending"
            )


def test_capability_keys_well_formed() -> None:
    for p in _projections():
        pid = p["id"]
        for key in p["capabilityKeys"]:
            prefix, sep, verb = key.partition(".")
            assert sep == "." and prefix == pid and verb in PROJECTION_CAPABILITY_VERBS, (
                f"{pid}: malformed capabilityKey {key!r} (expected {pid}.<verb> with "
                f"verb in {sorted(PROJECTION_CAPABILITY_VERBS)})"
            )


def test_validate_registry_schema_returns_empty() -> None:
    assert validate_registry_schema(_registry()) == []


# --- N1: schema negative fixtures (adversarial-verifier gap) -----------------


def _schema_messages(reg: dict) -> list[str]:
    return [v.message for v in validate_registry_schema(reg)]


def test_negative_duplicate_id_reported() -> None:
    reg = _mk_reg([_entry("a"), _entry("a")])
    assert any("projection ids must be unique" in m for m in _schema_messages(reg))


def test_negative_owns_canonical_truth_true_reported() -> None:
    reg = _mk_reg([_entry("a", ownsCanonicalTruth=True)])
    assert any("ownsCanonicalTruth must be False" in m for m in _schema_messages(reg))


def test_negative_missing_required_field_reported() -> None:
    entry = _entry("a")
    del entry["inputRefs"]
    reg = _mk_reg([entry])
    assert any("missing required field 'inputRefs'" in m for m in _schema_messages(reg))


def test_negative_bad_enum_reported() -> None:
    reg = _mk_reg([_entry("a", projectionKind="not_a_kind")])
    assert any("unknown projectionKind 'not_a_kind'" in m for m in _schema_messages(reg))


def test_negative_pending_bad_kind_reported() -> None:
    pending = {
        "id": "future_x",
        "kind": "not_a_real_kind",
        "reason": "wip",
        "resolvesInProjection": "a",
    }
    reg = _mk_reg([_entry("a", pendingAuthority=[pending])])
    assert any("pending kind 'not_a_real_kind'" in m for m in _schema_messages(reg))


def test_negative_pending_bad_resolves_in_projection_reported() -> None:
    pending = {
        "id": "future_x",
        "kind": "spine",
        "reason": "wip",
        "resolvesInProjection": "WRONG_PROJECTION",
    }
    reg = _mk_reg([_entry("a", pendingAuthority=[pending])])
    assert any(
        "resolvesInProjection 'WRONG_PROJECTION'" in m for m in _schema_messages(reg)
    )


def test_negative_relabelled_dangling_pending_reported() -> None:
    # A now-resolved projection re-declared as kind:"spine" must NOT dodge the
    # dangling ratchet: the id-space union (SPINE_INDEX ∪ registry ids) decides,
    # not the declared ``kind`` label. Exercises validate_dependency_dag.
    pending = {
        "id": "profile360",
        "kind": "spine",
        "reason": "stale",
        "resolvesInProjection": "a",
    }
    reg = _mk_reg([_entry("a", pendingAuthority=[pending]), _entry("profile360")])
    violations = validate_dependency_dag(reg)
    assert any(
        v.rule == "order_resilience"
        and v.severity == "error"
        and "dangling pending projection" in v.message
        and "profile360" in v.message
        for v in violations
    )
