"""Intelligence Projection dependency-DAG tests (P0.2, group 2).

Negative fixtures prove the DAG rules catch self-dependencies, undeclared
unknown dependencies, cycles (reporting the cycle path), implemented-with-
pending, and dangling pending declarations. A positive test proves the REAL
18-projection registry is acyclic and passes ``validate_dependency_dag``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.intelligence_projection_validation import (  # noqa: E402
    Violation,
    validate_dependency_dag,
)

_REGISTRY_JSON = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"
)


def _mk_reg(entries: list[dict]) -> dict:
    """Build a minimal in-memory registry fixture for DAG validation."""
    return {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "projections": entries,
    }


def _entry(
    pid: str,
    deps: list[str] | None = None,
    optional: list[str] | None = None,
    state: str = "in_flight",
    pending_auth: list[dict] | None = None,
    pending_ref: list[dict] | None = None,
) -> dict:
    return {
        "id": pid,
        "implementationState": state,
        "projectionDependencies": deps or [],
        "optionalProjectionDependencies": optional or [],
        "pendingAuthority": pending_auth or [],
        "pendingReference": pending_ref or [],
    }


def _messages(violations: list[Violation]) -> list[str]:
    return [v.message for v in violations]


def test_self_dependency_reported() -> None:
    reg = _mk_reg([_entry("a", deps=["a"])])
    violations = validate_dependency_dag(reg)
    assert any("self-dependency" in m for m in _messages(violations))
    assert any(v.rule == "dependency_dag" and v.severity == "error" for v in violations)


def test_unknown_undeclared_dependency_reported() -> None:
    reg = _mk_reg([_entry("a", deps=["nope"])])
    violations = validate_dependency_dag(reg)
    assert any(
        "neither a registry id nor declared pending" in m for m in _messages(violations)
    )


def test_cycle_reported_with_path() -> None:
    reg = _mk_reg([_entry("a", deps=["b"]), _entry("b", deps=["a"])])
    violations = validate_dependency_dag(reg)
    cycle_messages = [m for m in _messages(violations) if "dependency cycle" in m]
    assert len(cycle_messages) == 1
    assert cycle_messages[0] == "dependency cycle: a -> b -> a"


def test_longer_cycle_reports_full_path() -> None:
    reg = _mk_reg(
        [
            _entry("a", deps=["b"]),
            _entry("b", deps=["c"]),
            _entry("c", deps=["a"]),
        ]
    )
    violations = validate_dependency_dag(reg)
    cycle_messages = [m for m in _messages(violations) if "dependency cycle" in m]
    assert len(cycle_messages) == 1
    assert cycle_messages[0] == "dependency cycle: a -> b -> c -> a"


def test_required_cycle_is_error() -> None:
    reg = _mk_reg([_entry("a", deps=["b"]), _entry("b", deps=["a"])])
    violations = validate_dependency_dag(reg)
    errors = [v for v in violations if v.severity == "error"]
    assert any(
        v.rule == "dependency_dag"
        and v.message == "dependency cycle: a -> b -> a"
        for v in errors
    )
    # a fully-required cycle is an ordering deadlock: no benign warning.
    assert not any(v.severity == "warning" for v in violations)


def test_optional_cycle_is_warning_not_error() -> None:
    # a requires b; b optional-> a → the only cycle is via an optional edge.
    reg = _mk_reg([_entry("a", deps=["b"]), _entry("b", optional=["a"])])
    violations = validate_dependency_dag(reg)
    warnings = [v for v in violations if v.severity == "warning"]
    assert not any(v.severity == "error" for v in violations)
    assert len(warnings) == 1
    assert warnings[0].rule == "dependency_dag"
    assert warnings[0].message == "dependency cycle (via optional edge): a -> b -> a(optional)"


def test_relationship_style_optional_cycle_is_warning() -> None:
    # relationship360-style: r optional-> e while e required-> r. The DFS
    # reports the cycle starting from the lexicographically smallest node (e).
    reg = _mk_reg([_entry("r", optional=["e"]), _entry("e", deps=["r"])])
    violations = validate_dependency_dag(reg)
    warnings = [v for v in violations if v.severity == "warning"]
    assert not any(v.severity == "error" for v in violations)
    assert len(warnings) == 1
    assert warnings[0].message == "dependency cycle (via optional edge): e -> r -> e(optional)"


def test_implemented_with_pending_reported() -> None:
    pending = [{"id": "future_spine", "kind": "spine", "reason": "wip", "resolvesInProjection": "a"}]
    reg = _mk_reg([_entry("a", state="implemented", pending_auth=pending)])
    violations = validate_dependency_dag(reg)
    assert any(
        "implemented projection must have zero pending" in m for m in _messages(violations)
    )


def test_implemented_with_unresolved_dependency_reported() -> None:
    reg = _mk_reg([_entry("a", state="implemented", deps=["missing_projection"])])
    violations = validate_dependency_dag(reg)
    assert any(
        "implemented projection has unresolved dependencies" in m for m in _messages(violations)
    )


def test_in_flight_with_pending_ok() -> None:
    pending = [{"id": "pending_spine", "kind": "spine", "reason": "wip", "resolvesInProjection": "a"}]
    reg = _mk_reg([_entry("a", state="in_flight", pending_auth=pending)])
    assert validate_dependency_dag(reg) == []


def test_dangling_pending_projection_reported() -> None:
    pending = [{"id": "profile360", "kind": "projection", "reason": "stale", "resolvesInProjection": "a"}]
    reg = _mk_reg([_entry("a", pending_ref=pending), _entry("profile360")])
    violations = validate_dependency_dag(reg)
    assert any(
        "dangling pending projection" in m and "profile360" in m
        for m in _messages(violations)
    )


def test_dangling_pending_spine_reported() -> None:
    pending = [{"id": "contract_spine", "kind": "spine", "reason": "stale", "resolvesInProjection": "a"}]
    reg = _mk_reg([_entry("a", pending_auth=pending)])
    violations = validate_dependency_dag(reg)
    assert any(
        "dangling pending spine" in m and "contract_spine" in m
        for m in _messages(violations)
    )


def test_real_registry_has_no_required_cycles() -> None:
    reg = json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))
    violations = validate_dependency_dag(reg)
    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]

    # No ordering deadlock: the required dependency graph is acyclic.
    assert errors == []

    # The real registry intentionally has optional↔required union cycles
    # (e.g. relationship360 optional↔economic360). They surface as labelled
    # warnings, never errors.
    assert len(warnings) >= 4
    for v in warnings:
        assert v.rule == "dependency_dag"
        assert "dependency cycle (via optional edge)" in v.message
        assert "(optional)" in v.message

    # Every optional edge that participates in a union cycle must be visible,
    # labelled with its (optional) marker, somewhere in the reported paths.
    joined = "\n".join(v.message for v in warnings)
    for optional_edge in (
        "relationship360 -> economic360(optional)",
        "relationship360 -> communication360(optional)",
        "relationship360 -> social360(optional)",
        "relationship360 -> risk360(optional)",
        "profile360 -> risk360(optional)",
    ):
        assert optional_edge in joined, f"missing optional-edge cycle warning for {optional_edge}"
