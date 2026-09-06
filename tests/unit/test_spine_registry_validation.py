"""Spine Registry validator tests (Spine P0, Wave 2A).

Positive and negative coverage for ``scripts/lib/spine_registry_validation.py``:

- a small synthetic PASSING registry (one implemented truth authority with a
  full 14-check conformance map, one pending row with an unresolvedRefs
  declaration, one program_capability row with ``conformance == {}``) that is
  green across every rule group;
- NEGATIVE fixtures that each provoke a specific Violation id (duplicate id,
  bad plane, unresolved/self/cyclic dependencies, surface / readinessKey /
  contract-refId resolution failures, conformance map defects, the P6
  state-flip gap, malformed unresolvedRefs, a parallel-id collision, lifecycle
  and ownership defects);
- an INTEGRATION test asserting the committed
  ``packages/shared/contracts/spine-registry.json`` passes with ZERO
  ``severity=="error"`` violations;
- a CLI subprocess test asserting exit 0 on the real registry.

Fixtures are built in memory against the REAL cross-registry context loaded by
``load_context()`` (mirroring the projection-validator test style).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.spine_registry_validation import (  # noqa: E402
    CONFORMANCE_CHECK_IDS,
    Violation,
    load_context,
    validate_all,
    validate_conformance_gate,
    validate_cross_registry,
    validate_dependency_dag,
    validate_inventory_honesty,
    validate_lifecycle_honesty,
    validate_ownership,
    validate_registry_schema,
)

_REGISTRY_JSON = REPO_ROOT / "packages" / "shared" / "contracts" / "spine-registry.json"

_LOWER_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

_PLANES = ["governance_contract", "relationship_graph", "resolution_canonical_data"]
_KINDS = ["truth_authority", "program_capability"]
_STATES = ["pending", "in_flight", "implemented", "canonical"]
_POLICIES = ["read_only", "canonical_gateway_only"]

_REQUIRED_FIELDS = frozenset(
    {
        "id",
        "displayName",
        "description",
        "plane",
        "spineKind",
        "implementationState",
        "ownsCanonicalTruth",
        "authorityDeclaration",
        "nonOwnershipStatement",
        "canonicalContractRefs",
        "ports",
        "adapters",
        "dependencies",
        "graphMutationPolicy",
        "tenantBoundary",
        "lifecycle",
        "readinessKey",
        "surfaces",
        "securityCompliance",
        "observabilityRecovery",
        "conformance",
        "unresolvedRefs",
        "legacyBindings",
        "implementationBlueprint",
    }
)


def _conformance(**overrides: str) -> dict:
    """A full 14-check conformance map, all ``"open"`` by default."""
    return {check: overrides.get(check, "open") for check in CONFORMANCE_CHECK_IDS}


def _mk_reg(entries: list[dict], **top_overrides: object) -> dict:
    """Minimal in-memory spine registry with the vocab arrays the schema gate
    needs plus the canonical 14 conformanceChecks."""
    reg = {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "description": "synthetic spine registry fixture",
        "planes": list(_PLANES),
        "spineKinds": list(_KINDS),
        "implementationStates": list(_STATES),
        "graphMutationPolicies": list(_POLICIES),
        "conformanceChecks": [{"id": check, "title": check} for check in CONFORMANCE_CHECK_IDS],
        "spines": entries,
    }
    reg.update(top_overrides)
    return reg


def _spine(spine_id: str, **overrides: object) -> dict:
    """A fully-populated per-entry fixture; override only the field under test."""
    base = {
        "id": spine_id,
        "displayName": spine_id,
        "description": f"Fixture spine {spine_id}.",
        "plane": "governance_contract",
        "spineKind": "truth_authority",
        "implementationState": "implemented",
        "ownsCanonicalTruth": True,
        "authorityDeclaration": "Authoritatively owns the fixture domain.",
        "nonOwnershipStatement": "Does not own any canonical fact outside the fixture domain.",
        "canonicalContractRefs": [
            {
                "registry": "packages/shared/contracts/consent-registry.json",
                "refIds": ["analytics"],
            }
        ],
        "ports": {"consumed": [], "published": ["fixture_port"]},
        "adapters": [],
        "dependencies": {"hard": [], "soft": [], "runtime": [], "policy": []},
        "graphMutationPolicy": "read_only",
        "tenantBoundary": {
            "tenantScoped": True,
            "consentRequired": False,
            "rightsBoundary": "fixture_boundary",
        },
        "lifecycle": {"typedDegradation": False, "recomputeSafe": True, "replaySupported": False},
        "readinessKey": None,
        "surfaces": [],
        "securityCompliance": {
            "tenantIsolation": "tenant_scoped",
            "exportClass": "internal",
            "distillationRisk": "low",
        },
        "observabilityRecovery": {"healthKeys": ["fixture_health"], "replaySupported": False},
        "conformance": _conformance(),
        "unresolvedRefs": [],
        "legacyBindings": {
            "aliases": [spine_id],
            "services": ["packages/shared/contracts"],
            "migrationMode": "formalize_existing",
        },
        "implementationBlueprint": None,
    }
    base.update(overrides)
    return base


def _registry() -> dict:
    return json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))


def _errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error"]


def _ids(violations: list[Violation]) -> set[str]:
    return {v.id for v in violations}


def _passing_registry() -> dict:
    """Small synthetic registry that must be green across every rule group.

    1. one implemented truth_authority with a full 14-check conformance map and
       a canonical-contract ref that resolves (consent purpose ``analytics``);
    2. one pending truth_authority that declares where it is heading via an
       unresolvedRefs entry (net_new, no formalize_existing contradiction);
    3. one program_capability row whose ``conformance`` is ``{}``.
    """
    implemented = _spine(
        "fixture_truth_authority",
        plane="relationship_graph",
        ownsCanonicalTruth=True,
    )
    pending = _spine(
        "fixture_pending_authority",
        implementationState="pending",
        ownsCanonicalTruth=False,
        legacyBindings={
            "aliases": ["fixture_pending_authority"],
            "services": [],
            "migrationMode": "net_new",
        },
        unresolvedRefs=[
            {
                "ref": "fixture pending authority",
                "kind": "spine",
                "reason": "fixture pending until the spine plane formalizes it",
                "resolvesIn": "Spine P0 fixture phase",
            }
        ],
    )
    program = _spine(
        "fixture_capability_program",
        spineKind="program_capability",
        implementationState="in_flight",
        ownsCanonicalTruth=False,
        conformance={},
        legacyBindings={
            "aliases": ["fixture_capability_program"],
            "services": [],
            "migrationMode": "net_new",
        },
    )
    return _mk_reg([implemented, pending, program])


# --- positive: real registry -------------------------------------------------


def test_registry_has_34_spines() -> None:
    # 33 rows shipped from the spine lane + infrastructure_model, added during
    # the re-cut onto the 360 foundation (fced2960) whose resolved spine plane
    # already included it (infrastructure360 S4 reads over it).
    reg = _registry()
    spines = reg["spines"]
    assert len(spines) == 34
    ids = [s["id"] for s in spines]
    assert len(ids) == len(set(ids))
    for spine_id in ids:
        assert _LOWER_SNAKE_RE.fullmatch(spine_id), f"id {spine_id!r} is not lower_snake"


def test_every_required_entry_field_present_on_real_registry() -> None:
    for spine in _registry()["spines"]:
        for field in _REQUIRED_FIELDS:
            assert field in spine, f"{spine['id']}: missing required field {field!r}"


def test_real_registry_passes_with_zero_errors() -> None:
    violations = validate_all(_registry())
    assert [v for v in violations if v.severity == "error"] == []
    # Advisory warnings are allowed, but they must be genuinely few.
    assert sum(1 for v in violations if v.severity == "warning") <= 10


# --- positive: synthetic -----------------------------------------------------


def test_synthetic_passing_registry_green_across_all_groups() -> None:
    violations = validate_all(_passing_registry())
    assert violations == [], [str(v) for v in violations]


# --- registry_schema negatives ------------------------------------------------


def _schema_errors(reg: dict) -> list[Violation]:
    return _errors(validate_registry_schema(reg))


def test_negative_duplicate_id_reported() -> None:
    reg = _mk_reg([_spine("a"), _spine("a")])
    assert "registry_schema.duplicate_spine_id" in _ids(_schema_errors(reg))


def test_negative_bad_plane_reported() -> None:
    reg = _mk_reg([_spine("a", plane="not_a_plane")])
    assert "registry_schema.unknown_plane" in _ids(_schema_errors(reg))


def test_negative_bad_spine_kind_reported() -> None:
    reg = _mk_reg([_spine("a", spineKind="not_a_kind")])
    assert "registry_schema.unknown_spine_kind" in _ids(_schema_errors(reg))


def test_negative_missing_required_field_reported() -> None:
    entry = _spine("a")
    del entry["canonicalContractRefs"]
    reg = _mk_reg([entry])
    assert "registry_schema.missing_entry_field" in _ids(_schema_errors(reg))


# --- dependency_dag negatives -------------------------------------------------


def test_negative_dependency_ref_not_a_spine_id_reported() -> None:
    deps = {"hard": ["missing_spine"], "soft": [], "runtime": [], "policy": []}
    reg = _mk_reg([_spine("a", dependencies=deps)])
    violations = validate_dependency_dag(reg)
    assert any(
        v.id == "dependency_dag.unresolved_dependency" and v.severity == "error" for v in violations
    )


def test_negative_self_dependency_reported() -> None:
    deps = {"hard": ["a"], "soft": [], "runtime": [], "policy": []}
    reg = _mk_reg([_spine("a", dependencies=deps)])
    violations = validate_dependency_dag(reg)
    assert any(v.id == "dependency_dag.self_dependency" for v in _errors(violations))


def test_negative_hard_dependency_cycle_reported() -> None:
    a = _spine("a", dependencies={"hard": ["b"], "soft": [], "runtime": [], "policy": []})
    b = _spine("b", dependencies={"hard": ["a"], "soft": [], "runtime": [], "policy": []})
    violations = validate_dependency_dag(_mk_reg([a, b]))
    assert any(
        v.id == "dependency_dag.cycle" and v.severity == "error" and "cycle" in v.message
        for v in violations
    )


def test_negative_unknown_dependency_kind_reported() -> None:
    deps = {"hard": [], "optional": ["a"]}
    reg = _mk_reg([_spine("a", dependencies=deps)])
    violations = validate_dependency_dag(reg)
    assert any(v.id == "dependency_dag.unknown_dependency_kind" for v in _errors(violations))


# --- cross_registry negatives -------------------------------------------------


def _cross_errors(reg: dict) -> list[Violation]:
    return _errors(validate_cross_registry(reg, load_context()))


def test_negative_surface_token_not_in_surface_registry_reported() -> None:
    reg = _mk_reg([_spine("a", surfaces=["definitely_not_a_surface"])])
    assert "cross_registry.surface_unresolved" in _ids(_cross_errors(reg))


def test_negative_readiness_key_not_a_token_reported() -> None:
    reg = _mk_reg([_spine("a", readinessKey="definitely_not_a_token")])
    assert "cross_registry.readiness_key_unresolved" in _ids(_cross_errors(reg))


def test_negative_contract_ref_id_not_in_owning_registry_reported() -> None:
    refs = [
        {
            "registry": "packages/shared/contracts/consent-registry.json",
            "refIds": ["definitely_not_a_purpose"],
        }
    ]
    reg = _mk_reg([_spine("a", canonicalContractRefs=refs)])
    assert "cross_registry.contract_ref_id_unresolved" in _ids(_cross_errors(reg))


def test_negative_contract_registry_path_missing_reported() -> None:
    refs = [{"registry": "packages/shared/contracts/no-such-registry.json", "refIds": ["x"]}]
    reg = _mk_reg([_spine("a", canonicalContractRefs=refs)])
    assert "cross_registry.contract_registry_missing" in _ids(_cross_errors(reg))


def test_negative_legacy_service_missing_is_an_error() -> None:
    """The tetris inventory gate is hard: a spine row must bind to machinery
    that exists on disk, or declare the dependency pending."""
    bindings = {
        "aliases": ["a"],
        "services": ["docs/source-of-truth/NO_SUCH_BLUEPRINT.md"],
        "migrationMode": "formalize_existing",
    }
    reg = _mk_reg([_spine("a", legacyBindings=bindings)])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.id == "cross_registry.legacy_service_missing" and v.severity == "error"
        for v in violations
    )


def test_negative_unresolved_ref_missing_reason_and_resolves_in_reported() -> None:
    unresolved = [{"ref": "future thing", "kind": "spine", "reason": "wip"}]
    reg = _mk_reg([_spine("a", unresolvedRefs=unresolved)])
    assert "cross_registry.unresolved_ref_incomplete" in _ids(_cross_errors(reg))


def test_negative_unresolved_ref_bad_kind_reported() -> None:
    unresolved = [
        {"ref": "future thing", "kind": "not_a_kind", "reason": "wip", "resolvesIn": "later"}
    ]
    reg = _mk_reg([_spine("a", unresolvedRefs=unresolved)])
    assert "cross_registry.unresolved_ref_kind" in _ids(_cross_errors(reg))


def test_negative_parallel_id_collision_reported() -> None:
    # ``profile360`` is an owned surface id — a spine row re-defining it is a
    # parallel-registry violation (no cross-plane homonym exception applies).
    reg = _mk_reg([_spine("profile360")])
    assert "cross_registry.parallel_id_collision" in _ids(_cross_errors(reg))


def test_positive_cross_plane_homonyms_allowed() -> None:
    # ``graph`` (exposed through the ``graph`` surface) and ``consent`` (the
    # authority over the ``consent`` event family) are documented exceptions.
    graph = _spine("graph", surfaces=["graph"])
    consent = _spine("consent")
    violations = _cross_errors(_mk_reg([graph, consent]))
    assert "cross_registry.parallel_id_collision" not in _ids(violations)


# --- conformance_gate negatives -----------------------------------------------


def _gate_errors(reg: dict) -> list[Violation]:
    return _errors(validate_conformance_gate(reg))


def test_negative_conformance_missing_a_check_reported() -> None:
    conf = _conformance()
    conf.pop("graph_mutation_policy")
    reg = _mk_reg([_spine("a", conformance=conf)])
    assert "conformance_gate.missing_check" in _ids(_gate_errors(reg))


def test_negative_conformance_unexpected_check_reported() -> None:
    conf = _conformance()
    conf["not_a_canonical_check"] = "open"
    reg = _mk_reg([_spine("a", conformance=conf)])
    assert "conformance_gate.unexpected_check" in _ids(_gate_errors(reg))


def test_negative_conformance_invalid_value_reported() -> None:
    conf = _conformance(graph_mutation_policy="half_done")
    reg = _mk_reg([_spine("a", conformance=conf)])
    assert "conformance_gate.invalid_conformance_value" in _ids(_gate_errors(reg))


def test_negative_program_row_with_nonempty_conformance_reported() -> None:
    reg = _mk_reg(
        [_spine("capability_program", spineKind="program_capability", conformance=_conformance())]
    )
    assert "conformance_gate.program_nonempty_conformance" in _ids(_gate_errors(reg))


def test_negative_canonical_state_with_open_conformance_reported() -> None:
    # P6: a state flip to "canonical" with an open gap is a hard error.
    reg = _mk_reg([_spine("a", implementationState="canonical", conformance=_conformance())])
    assert "conformance_gate.state_flip_open_gap" in _ids(_gate_errors(reg))


def test_positive_verified_conformance_allows_canonical_state() -> None:
    reg = _mk_reg(
        [
            _spine(
                "a",
                implementationState="canonical",
                conformance=_conformance(**{c: "verified" for c in CONFORMANCE_CHECK_IDS}),
            )
        ]
    )
    assert _gate_errors(reg) == []


# --- lifecycle_honesty negatives ----------------------------------------------


def test_negative_pending_without_declaration_reported() -> None:
    reg = _mk_reg([_spine("a", implementationState="pending", unresolvedRefs=[])])
    violations = validate_lifecycle_honesty(reg)
    assert any(
        v.id == "lifecycle_honesty.pending_without_declaration" and v.severity == "error"
        for v in violations
    )


def test_negative_non_boolean_lifecycle_reported() -> None:
    lifecycle = {"typedDegradation": False, "recomputeSafe": "yes", "replaySupported": False}
    reg = _mk_reg([_spine("a", lifecycle=lifecycle)])
    violations = validate_lifecycle_honesty(reg)
    assert any(v.id == "lifecycle_honesty.non_boolean_lifecycle" for v in _errors(violations))


# --- ownership negatives ------------------------------------------------------


def test_negative_missing_authority_declaration_reported() -> None:
    reg = _mk_reg([_spine("a", authorityDeclaration="  ")])
    violations = validate_ownership(reg)
    assert "ownership.missing_authority_declaration" in _ids(_errors(violations))


def test_negative_missing_non_ownership_statement_reported() -> None:
    reg = _mk_reg([_spine("a", nonOwnershipStatement="")])
    violations = validate_ownership(reg)
    assert "ownership.missing_non_ownership_statement" in _ids(_errors(violations))


def test_negative_bad_migration_mode_reported() -> None:
    bindings = {"aliases": ["a"], "services": [], "migrationMode": "not_a_mode"}
    reg = _mk_reg([_spine("a", legacyBindings=bindings)])
    violations = validate_ownership(reg)
    assert "ownership.unknown_migration_mode" in _ids(_errors(violations))


def test_negative_missing_legacy_bindings_reported() -> None:
    reg = _mk_reg([_spine("a", legacyBindings=None)])
    violations = validate_ownership(reg)
    assert "ownership.missing_legacy_bindings" in _ids(_errors(violations))


# --- inventory_honesty --------------------------------------------------------


def test_formalize_existing_with_pending_is_a_warning() -> None:
    bindings = {"aliases": ["a"], "services": [], "migrationMode": "formalize_existing"}
    reg = _mk_reg([_spine("a", implementationState="pending", legacyBindings=bindings)])
    violations = validate_inventory_honesty(reg, load_context())
    assert any(
        v.id == "inventory_honesty.formalize_existing_pending" and v.severity == "warning"
        for v in violations
    )


# --- CLI ----------------------------------------------------------------------


def test_cli_exits_zero_on_real_registry() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validate_spine_registry.py"),
            "--check",
            "--registry",
            str(_REGISTRY_JSON),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
