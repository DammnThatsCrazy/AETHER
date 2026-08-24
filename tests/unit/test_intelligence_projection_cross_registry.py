"""Intelligence Projection cross-registry tests (P0.8, group 4).

Negative fixtures prove the cross-registry rule group catches undeclared
unresolved surface / metric refs, surfaces whose supportedTemporalModes are not
supported by the projection's surfaces, malformed capabilityKeys, and
``canonical_gateway_only`` with an empty graph-mutation registry. The
order-resilience ratchet is proven both ways: declared-pending refs are legal
for in_flight projections, and a pending declaration whose target now resolves
is a dangling declaration (error). An ``implemented`` projection can never
carry an unresolved-but-declared-pending ref.

Fixtures are built in memory (mirroring the ``_mk_reg``/``_entry`` pattern from
the DAG test) against the REAL cross-registry context (surface, metric and
graph-mutation registries) loaded by ``load_context()``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.intelligence_projection_validation import (  # noqa: E402
    Violation,
    load_context,
    validate_cross_registry,
    validate_dependency_dag,
)


def _mk_reg(entries: list[dict]) -> dict:
    """Minimal in-memory registry fixture for cross-registry validation."""
    return {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "graphMutationPolicies": ["read_only", "canonical_gateway_only"],
        "projections": entries,
    }


def _pending(pid: str, kind: str) -> dict:
    """A well-formed pending declaration fixture."""
    return {
        "id": pid,
        "kind": kind,
        "reason": "declared pending",
        "resolvesInProjection": "fixture",
    }


def _entry(
    pid: str,
    state: str = "in_flight",
    surfaces: list[str] | None = None,
    modes: list[str] | None = None,
    metrics: list[str] | None = None,
    capability_keys: list[str] | None = None,
    policy: str = "read_only",
    pending_auth: list[dict] | None = None,
    pending_ref: list[dict] | None = None,
    deps: list[str] | None = None,
) -> dict:
    return {
        "id": pid,
        "implementationState": state,
        "surfaceIds": surfaces or [],
        "supportedTemporalModes": modes or [],
        "metricRefs": metrics or [],
        "capabilityKeys": capability_keys or [],
        "graphMutationPolicy": policy,
        "pendingAuthority": pending_auth or [],
        "pendingReference": pending_ref or [],
        "projectionDependencies": deps or [],
        "optionalProjectionDependencies": [],
    }


def _messages(violations: list[Violation]) -> list[str]:
    return [v.message for v in violations]


def _errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error"]


# --- surface refs -----------------------------------------------------------


def test_bad_surface_ref_reported() -> None:
    reg = _mk_reg([_entry("a", surfaces=["definitely_not_a_surface"])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "cross_registry"
        and "neither a registered surface nor declared pending" in v.message
        for v in _errors(violations)
    )


def test_pending_surface_ok_for_in_flight() -> None:
    queued = _pending("queued_surface", "surface")
    reg = _mk_reg([_entry("a", surfaces=["queued_surface"], pending_ref=[queued])])
    assert validate_cross_registry(reg, load_context()) == []


def test_dangling_surface_pending_reported() -> None:
    # graph IS registered — a pending declaration for it is now a dangling
    # declaration ("remove it"), regardless of the declared kind label.
    stale = _pending("graph", "surface")
    reg = _mk_reg([_entry("a", surfaces=["graph"], pending_ref=[stale])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "order_resilience" and "dangling pending surface" in v.message
        for v in _errors(violations)
    )


# --- metric refs ------------------------------------------------------------


def test_bad_metric_ref_reported() -> None:
    reg = _mk_reg([_entry("a", metrics=["definitely_not_a_metric"])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "cross_registry"
        and "neither in metric-registry.json nor declared pending" in v.message
        for v in _errors(violations)
    )


def test_pending_metric_ok_for_in_flight() -> None:
    queued = _pending("queued_metric", "metric")
    reg = _mk_reg([_entry("a", metrics=["queued_metric"], pending_ref=[queued])])
    assert validate_cross_registry(reg, load_context()) == []


def test_dangling_metric_pending_reported() -> None:
    # revenue IS registered — a pending declaration for it is now dangling.
    stale = _pending("revenue", "metric")
    reg = _mk_reg([_entry("a", metrics=["revenue"], pending_ref=[stale])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "order_resilience" and "dangling pending metric" in v.message
        for v in _errors(violations)
    )


# --- supportedTemporalModes -------------------------------------------------


def test_bad_temporal_mode_reported() -> None:
    # graph supports window/as_of/relative — compare is not supported.
    reg = _mk_reg([_entry("a", surfaces=["graph"], modes=["compare"])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "cross_registry"
        and "not supported by any of the projection's surfaces" in v.message
        for v in _errors(violations)
    )


def test_good_temporal_modes_ok() -> None:
    reg = _mk_reg([_entry("a", surfaces=["graph"], modes=["window", "as_of", "relative"])])
    assert validate_cross_registry(reg, load_context()) == []


# --- capabilityKeys (projection-plane namespace) ----------------------------


def test_malformed_capability_key_wrong_verb_reported() -> None:
    reg = _mk_reg([_entry("a", capability_keys=["a.write"])])
    violations = validate_cross_registry(reg, load_context())
    assert any("malformed capabilityKey" in v.message for v in _errors(violations))


def test_malformed_capability_key_wrong_prefix_reported() -> None:
    reg = _mk_reg([_entry("a", capability_keys=["other.read"])])
    violations = validate_cross_registry(reg, load_context())
    assert any("malformed capabilityKey" in v.message for v in _errors(violations))


def test_well_formed_capability_keys_ok() -> None:
    reg = _mk_reg(
        [_entry("a", surfaces=["graph"], capability_keys=["a.read", "a.explore"])]
    )
    assert validate_cross_registry(reg, load_context()) == []


# --- graphMutationPolicy ----------------------------------------------------


def test_canonical_gateway_only_requires_mutation_registry() -> None:
    ctx_empty = dict(load_context())
    ctx_empty["graph_mutation_types"] = set()
    reg = _mk_reg([_entry("a", policy="canonical_gateway_only")])
    violations = validate_cross_registry(reg, ctx_empty)
    assert any(
        v.rule == "cross_registry"
        and "canonical_gateway_only requires a non-empty graph-mutation registry" in v.message
        for v in _errors(violations)
    )


def test_canonical_gateway_only_ok_with_real_mutation_registry() -> None:
    reg = _mk_reg([_entry("a", policy="canonical_gateway_only")])
    assert validate_cross_registry(reg, load_context()) == []


# --- implemented cannot lie -------------------------------------------------


def test_implemented_with_declared_pending_surface_reported() -> None:
    queued = _pending("queued_surface", "surface")
    reg = _mk_reg(
        [_entry("a", state="implemented", surfaces=["queued_surface"], pending_ref=[queued])]
    )
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "order_resilience"
        and "implemented projection declares pending surface" in v.message
        for v in _errors(violations)
    )


def test_implemented_with_declared_pending_metric_reported() -> None:
    queued = _pending("queued_metric", "metric")
    reg = _mk_reg(
        [_entry("a", state="implemented", metrics=["queued_metric"], pending_ref=[queued])]
    )
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "order_resilience"
        and "implemented projection declares pending metric" in v.message
        for v in _errors(violations)
    )


def test_well_formed_in_flight_entries_pass_cleanly() -> None:
    # A realistic in_flight row (resolved surfaces + metrics + capability keys)
    # must produce zero cross-registry violations.
    reg = _mk_reg(
        [
            _entry(
                "campaign360",
                surfaces=["campaign360", "comparison_workbench"],
                modes=["window", "compare", "relative"],
                metrics=["conversion_rate", "revenue"],
                capability_keys=["campaign360.read", "campaign360.explore"],
            )
        ]
    )
    assert validate_cross_registry(reg, load_context()) == []


# --- capabilityKeys: the `manage` verb is a live member of the verb set -----


def test_manage_verb_capability_key_accepted() -> None:
    # PROJECTION_CAPABILITY_VERBS == {read, explore, manage}. A key with the
    # `manage` verb must be accepted — the check must not be a dead
    # read/explore-only special case.
    reg = _mk_reg(
        [
            _entry(
                "cluster360",
                surfaces=["cluster360", "graph"],
                capability_keys=["cluster360.read", "cluster360.manage"],
            )
        ]
    )
    assert validate_cross_registry(reg, load_context()) == []


# --- kind-namespacing (a pending declaration's kind gates its id space) -----


def test_surface_pending_wrong_kind_not_accepted() -> None:
    # A pending declaration with kind="metric" does NOT namespace the surface id
    # space — the surfaceId is undeclared and must fail closed.
    wrong = _pending("queued_surface", "metric")
    reg = _mk_reg([_entry("a", surfaces=["queued_surface"], pending_ref=[wrong])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "cross_registry"
        and "neither a registered surface nor declared pending" in v.message
        for v in violations
    )


def test_metric_pending_wrong_kind_not_accepted() -> None:
    # A pending declaration with kind="surface" does NOT namespace the metric id
    # space — the metricRef is undeclared and must fail closed.
    wrong = _pending("queued_metric", "surface")
    reg = _mk_reg([_entry("a", metrics=["queued_metric"], pending_ref=[wrong])])
    violations = validate_cross_registry(reg, load_context())
    assert any(
        v.rule == "cross_registry"
        and "neither in metric-registry.json nor declared pending" in v.message
        for v in violations
    )


def test_projection_dependency_pending_wrong_kind_not_accepted() -> None:
    # A pending declaration with kind="spine" does NOT namespace the projection
    # id space — a projection dependency carrying the same id is still
    # undeclared and errors (dependency_dag rule group).
    wrong = _pending("earlier", "spine")
    reg = _mk_reg([_entry("a", deps=["earlier"], pending_ref=[wrong])])
    violations = validate_dependency_dag(reg)
    assert any(
        v.severity == "error"
        and "neither a registry id nor declared pending" in v.message
        for v in violations
    )


def test_projection_dependency_pending_kind_projection_accepted() -> None:
    # Same skip-ahead, declared with kind="projection" → legal (the dep is
    # namespaced into the projection id space).
    right = _pending("earlier", "projection")
    reg = _mk_reg([_entry("a", deps=["earlier"], pending_ref=[right])])
    assert validate_dependency_dag(reg) == []
