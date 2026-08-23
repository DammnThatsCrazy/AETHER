"""Intelligence Projection honesty-rule tests (P0.8, MINOR-4).

Dedicated coverage for the three rule groups that previously had no tests of
their own:

- ownership_integrity — canonicalAuthorities ⊆ AUTHORITY_INDEX (unknown
  authority → error); the projector-ownership registry may be an ``inputRef``
  but is never a canonical authority; declared-pending authorities are legal.
- surface_honesty — surfaceIds must be non-empty; an in_flight projection's
  RESOLVED surfaceIds (registered in the surface registry) must be declared in
  legacyBindings.surfaceIds. (Unregistered surfaces are the cross_registry
  rule's gate — ``surfaceIds ⊆ surface registry`` — not this rule's.)
- metric_honesty — the lib gates ONLY the measurement_360 / risk_360
  projectionKinds: a projection of those kinds declaring metricRefs must set
  requiresEvidence=True AND requiresLimitations=True. Non-measurement kinds are
  out of scope here (their metricRefs still resolve via cross_registry).

Positive: the REAL 18-projection registry passes all three rule groups.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.intelligence_projection_validation import (  # noqa: E402
    Violation,
    load_context,
    validate_metric_honesty,
    validate_ownership,
    validate_surface_honesty,
)

_REGISTRY_JSON = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"
)


def _mk_reg(entries: list[dict]) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "projections": entries,
    }


def _pending(pid: str, kind: str) -> dict:
    return {
        "id": pid,
        "kind": kind,
        "reason": "declared pending",
        "resolvesInProjection": "fixture",
    }


def _entry(pid: str, **overrides: object) -> dict:
    base = {
        "id": pid,
        "implementationState": "in_flight",
        "implementationBlueprint": "docs/ACCESS-CONTROL.md",
        "projectionKind": "entity_360",
        "canonicalAuthorities": ["graph", "evidence"],
        "surfaceIds": ["graph"],
        "metricRefs": [],
        "requiresEvidence": True,
        "requiresLimitations": True,
        "pendingAuthority": [],
        "pendingReference": [],
        "legacyBindings": {
            "routes": [],
            "surfaceIds": ["graph"],
            "services": [],
            "migrationMode": "adapter",
        },
    }
    base.update(overrides)
    return base


def _errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error"]


# --- ownership_integrity ----------------------------------------------------


def test_unknown_canonical_authority_reported() -> None:
    reg = _mk_reg([_entry("a", canonicalAuthorities=["not_in_authority_index"])])
    violations = validate_ownership(reg)
    assert any(
        v.rule == "ownership"
        and "not in AUTHORITY_INDEX nor declared pending" in v.message
        for v in _errors(violations)
    )


def test_projector_ownership_never_a_canonical_authority() -> None:
    reg = _mk_reg([_entry("a", canonicalAuthorities=["projector-ownership"])])
    violations = validate_ownership(reg)
    assert any(
        v.rule == "ownership"
        and "projector-ownership-registry may be an inputRef but never a canonical authority"
        in v.message
        for v in _errors(violations)
    )


def test_projector_ownership_legal_as_input_ref() -> None:
    # ownership only gates canonicalAuthorities — the projector-ownership
    # registry is legal as an inputRef (inputRefs are not checked here).
    reg = _mk_reg([_entry("a", inputRefs=["projector-ownership"])])
    assert validate_ownership(reg) == []


def test_pending_canonical_authority_is_legal() -> None:
    # A canonical authority not yet in AUTHORITY_INDEX is legal when declared
    # pending (the order-resilience escape hatch).
    reg = _mk_reg(
        [
            _entry(
                "a",
                canonicalAuthorities=["future_authority"],
                pendingAuthority=[_pending("future_authority", "spine")],
            )
        ]
    )
    assert validate_ownership(reg) == []


def test_valid_authority_set_passes() -> None:
    reg = _mk_reg([_entry("a", canonicalAuthorities=["graph", "evidence", "identity"])])
    assert validate_ownership(reg) == []


# --- surface_honesty --------------------------------------------------------


def test_empty_surface_ids_reported() -> None:
    reg = _mk_reg([_entry("a", surfaceIds=[])])
    violations = validate_surface_honesty(reg, load_context())
    assert any(
        v.rule == "surface_honesty" and "surfaceIds must be non-empty" in v.message
        for v in _errors(violations)
    )


def test_in_flight_resolved_surfaces_must_match_bindings() -> None:
    # Both graph and profile360 are registered surfaces; profile360 is resolved
    # but NOT declared in legacyBindings.surfaceIds → honesty violation.
    reg = _mk_reg(
        [
            _entry(
                "a",
                surfaceIds=["graph", "profile360"],
                legacyBindings={
                    "routes": [],
                    "surfaceIds": ["graph"],
                    "services": [],
                    "migrationMode": "adapter",
                },
            )
        ]
    )
    violations = validate_surface_honesty(reg, load_context())
    assert any(
        v.rule == "surface_honesty"
        and "not declared in legacyBindings.surfaceIds" in v.message
        and "profile360" in v.message
        for v in _errors(violations)
    )


def test_in_flight_resolved_surfaces_matching_bindings_ok() -> None:
    reg = _mk_reg([_entry("a", surfaceIds=["graph"])])
    assert validate_surface_honesty(reg, load_context()) == []


# --- metric_honesty (kind-scoped to measurement_360 / risk_360) -------------


def test_measurement_kind_metric_refs_require_evidence() -> None:
    reg = _mk_reg(
        [
            _entry(
                "a",
                projectionKind="measurement_360",
                metricRefs=["revenue"],
                requiresEvidence=False,
            )
        ]
    )
    violations = validate_metric_honesty(reg, load_context())
    assert any(
        v.rule == "metric_honesty" and "requiresEvidence=True" in v.message
        for v in _errors(violations)
    )


def test_risk_kind_metric_refs_require_limitations() -> None:
    reg = _mk_reg(
        [
            _entry(
                "a",
                projectionKind="risk_360",
                metricRefs=["revenue"],
                requiresLimitations=False,
            )
        ]
    )
    violations = validate_metric_honesty(reg, load_context())
    assert any(
        v.rule == "metric_honesty" and "requiresLimitations=True" in v.message
        for v in _errors(violations)
    )


def test_measurement_kind_metric_refs_with_requirements_ok() -> None:
    reg = _mk_reg(
        [_entry("a", projectionKind="measurement_360", metricRefs=["revenue"])]
    )
    assert validate_metric_honesty(reg, load_context()) == []


def test_non_measurement_kind_with_metric_refs_not_gated() -> None:
    # The lib's metric_honesty only gates measurement_360 / risk_360 kinds — an
    # entity_360 declaring metricRefs is NOT gated here (its metricRefs still
    # resolve through the cross_registry rule instead).
    reg = _mk_reg(
        [_entry("a", projectionKind="entity_360", metricRefs=["revenue"])]
    )
    assert validate_metric_honesty(reg, load_context()) == []


def test_measurement_kind_without_metric_refs_not_gated() -> None:
    reg = _mk_reg([_entry("a", projectionKind="measurement_360", requiresEvidence=False)])
    assert validate_metric_honesty(reg, load_context()) == []


# --- the real registry passes all three honesty rule groups -----------------


def test_real_registry_passes_all_honesty_rule_groups() -> None:
    reg = json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))
    ctx = load_context()
    results = {
        "ownership": validate_ownership(reg),
        "surface_honesty": validate_surface_honesty(reg, ctx),
        "metric_honesty": validate_metric_honesty(reg, ctx),
    }
    for rule, violations in results.items():
        errors = _errors(violations)
        assert errors == [], f"{rule}: {[v.message for v in errors]}"
