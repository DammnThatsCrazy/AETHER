"""Scenario coverage for the multidimensional readiness model.

Each test maps to a scenario in the readiness-refactor contract. The common
thread: a missing credential, unprovisioned infrastructure, an incomplete
dependency, a missing operational control, a failed environment run, or a
business gap must each be represented on its OWN dimension and must never
silently reduce repository-controlled implementation completion.
"""

from __future__ import annotations

import copy

import pytest

from scripts.lib.readiness_model import (
    BLOCKING_DISPOSITIONS,
    ELIGIBLE_DISPOSITIONS,
    completion_percent,
    evaluate_profile,
    evaluate_release_profile,
    feature_from_dict,
    load_model,
)

MODEL = load_model()


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def base_feature(**over) -> dict:
    """A complete, valid credential-turnkey feature record as a dict."""
    d = {
        "feature_id": "sample",
        "title": "Sample",
        "owning_system": "aether",
        "scope": {"id": "sample-v1", "version": 1, "title": "Sample V1", "target": "pilot"},
        "repository_ceiling": {"type": "CREDENTIAL_TURNKEY", "achieved": True},
        "implementation": {
            "state": "TURNKEY",
            "denominator": "in-scope controls",
            "controls": [
                {"id": "c1", "weight": 1, "satisfied": True},
                {"id": "c2", "weight": 1, "satisfied": True},
            ],
            "remaining_work": [],
        },
        "productionization": {
            "denominator": "in-scope controls",
            "controls": [{"id": "p1", "weight": 1, "satisfied": True}],
            "remaining_work": [],
        },
        "activation": {
            "state": "CREDENTIAL_WAITING",
            "blockers": [
                {
                    "type": "CREDENTIAL_WAITING",
                    "description": "needs a secret",
                    "owner": "ops",
                    "required_action": "insert secret",
                    "source_code_change_expected": False,
                    "affected_release_profiles": ["staging", "pilot", "production-lean", "production-scale"],
                }
            ],
        },
        "dependencies": {"hard": [], "soft": []},
        "environment_evidence": {
            "local": {"state": "VERIFIED", "credentialed": False},
            "ci": {"state": "VERIFIED", "credentialed": False},
            "staging": {"state": "BLOCKED_EXTERNAL", "credentialed": True},
        },
        "operational_ownership": {
            "team": "platform",
            "runbook": "docs/runbooks/sample.md",
            "dashboards": ["grafana:sample"],
            "alerts": ["pagerduty:sample"],
        },
        "business_readiness": {"applicable": False, "controls": []},
        "confidence": {"level": "HIGH"},
        "release_profiles": {
            "local": {"participation": "required", "implementation_floor": "VERIFIED", "productionization_required": False, "environment_gate": "local", "business_gate": False},
            "staging": {"participation": "required", "implementation_floor": "TURNKEY", "productionization_required": True, "environment_gate": "staging", "business_gate": False},
            "pilot": {"participation": "required", "implementation_floor": "TURNKEY", "productionization_required": True, "environment_gate": "pilot", "business_gate": True},
            "production-lean": {"participation": "required", "implementation_floor": "TURNKEY", "productionization_required": True, "environment_gate": "production", "business_gate": True},
            "production-scale": {"participation": "required", "implementation_floor": "TURNKEY", "productionization_required": True, "environment_gate": "scale", "business_gate": True},
        },
    }
    return _merge(d, over)


def ev(feature_dict: dict, profile: str):
    feat = feature_from_dict(feature_dict)
    return feat, evaluate_profile(feat, MODEL.profiles[profile], MODEL)


# -- Scenario 1: credential-turnkey feature ---------------------------------
def test_scenario_1_credential_turnkey():
    feat, e = ev(base_feature(), "staging")
    assert feat.implementation.percent() == 100.0
    assert feat.repository_ceiling.achieved is True
    assert feat.activation_state == "CREDENTIAL_WAITING"
    assert e.disposition == "READY_TO_ACTIVATE"
    assert e.hard_blockers == []  # no code blocker


# -- Scenario 2: infrastructure-turnkey feature -----------------------------
def test_scenario_2_infrastructure_turnkey():
    f = base_feature(
        repository_ceiling={"type": "INFRASTRUCTURE_TURNKEY", "achieved": True},
        activation={
            "state": "INFRASTRUCTURE_WAITING",
            "blockers": [
                {
                    "type": "INFRASTRUCTURE_WAITING",
                    "description": "terraform not applied",
                    "owner": "ops",
                    "required_action": "apply plan",
                    "source_code_change_expected": False,
                    "affected_release_profiles": ["staging", "pilot", "production-lean", "production-scale"],
                }
            ],
        },
    )
    feat, e = ev(f, "production-lean")
    assert feat.implementation.percent() == 100.0  # not reduced by missing infra
    assert feat.repository_ceiling.achieved is True
    assert feat.activation_state == "INFRASTRUCTURE_WAITING"
    assert e.disposition == "READY_TO_ACTIVATE"
    assert e.hard_blockers == []


# -- Scenario 3: code exists but is not reachable ---------------------------
def test_scenario_3_not_runtime_integrated():
    f = base_feature(
        repository_ceiling={"type": "CODE_COMPLETE", "achieved": True},
        implementation={
            "state": "IMPLEMENTED",
            "denominator": "in-scope controls",
            "controls": [
                {"id": "c1", "weight": 1, "satisfied": True},
                {"id": "runtime-wiring", "weight": 1, "satisfied": False},
            ],
            "remaining_work": ["wire the real runtime path"],
        },
        activation={"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        environment_evidence={"local": {"state": "VERIFIED", "credentialed": False}, "ci": {"state": "VERIFIED", "credentialed": False}},
    )
    feat, e = ev(f, "staging")
    assert feat.implementation.state != "RUNTIME_INTEGRATED"
    assert feat.implementation.state != "TURNKEY"
    assert e.disposition == "BLOCKED_BY_CODE"
    assert any("repository work" in b or "below" in b or "completion" in b for b in e.hard_blockers)


# -- Scenario 4: tests pass but productionization incomplete ----------------
def test_scenario_4_productionization_incomplete():
    f = base_feature(
        activation={"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        productionization={
            "denominator": "in-scope controls",
            "controls": [
                {"id": "logs", "weight": 1, "satisfied": True},
                {"id": "monitoring", "weight": 1, "satisfied": False},
                {"id": "rollback", "weight": 1, "satisfied": False},
            ],
            "remaining_work": ["add monitoring", "add rollback runbook"],
        },
        environment_evidence={"local": {"state": "VERIFIED", "credentialed": False}, "ci": {"state": "VERIFIED", "credentialed": False}, "staging": {"state": "NOT_ATTEMPTED", "credentialed": True}},
    )
    feat, e = ev(f, "staging")
    assert feat.implementation.percent() == 100.0
    assert feat.productionization.percent() < 100.0
    assert e.disposition == "BLOCKED_BY_PRODUCTIONIZATION"


# -- Scenario 5: staging is unavailable -------------------------------------
def test_scenario_5_staging_unavailable():
    feat, e = ev(base_feature(), "staging")
    assert feat.implementation.percent() == 100.0
    assert feat.environment_evidence["staging"].state == "BLOCKED_EXTERNAL"
    assert e.disposition in {"READY_TO_ACTIVATE", "READY_TO_VALIDATE"}
    # confidence dimension is independent of implementation completion
    assert feat.confidence.level in {"UNPROVEN", "LOW", "MODERATE", "HIGH", "VERY_HIGH"}


def test_scenario_5_staging_ready_to_validate_when_activated():
    # Activation clear, environment active but evidence not captured yet.
    f = base_feature(
        activation={"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        environment_evidence={
            "local": {"state": "VERIFIED", "credentialed": False},
            "ci": {"state": "VERIFIED", "credentialed": False},
            "staging": {"state": "NOT_ATTEMPTED", "credentialed": True},
        },
    )
    _, e = ev(f, "staging")
    assert e.disposition == "READY_TO_VALIDATE"


# -- Scenario 6: dependency is incomplete -----------------------------------
def test_scenario_6_dependency_incomplete():
    f = base_feature(
        activation={"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        dependencies={"hard": [{"feature_id": "identity-resolution", "state": "WAITING", "prevents": ["release"]}]},
        environment_evidence={
            "local": {"state": "VERIFIED", "credentialed": False},
            "ci": {"state": "VERIFIED", "credentialed": False},
            "staging": {"state": "VERIFIED", "credentialed": True, "verification_method": "credentialed run"},
        },
    )
    feat, e = ev(f, "staging")
    # Intrinsic implementation stays complete; effective readiness is dep-blocked.
    assert feat.implementation.percent() == 100.0
    assert e.intrinsic_disposition not in {"BLOCKED_BY_DEPENDENCY"}
    assert e.intrinsic_disposition in ELIGIBLE_DISPOSITIONS
    assert e.disposition == "BLOCKED_BY_DEPENDENCY"


# -- Scenario 7: business readiness incomplete ------------------------------
def test_scenario_7_business_readiness_pending():
    f = base_feature(
        activation={"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        environment_evidence={
            "local": {"state": "VERIFIED", "credentialed": False},
            "ci": {"state": "VERIFIED", "credentialed": False},
            "pilot": {"state": "VERIFIED", "credentialed": True},
        },
        business_readiness={
            "applicable": True,
            "denominator": "commercial controls",
            "controls": [
                {"id": "legal", "weight": 1, "satisfied": False},
                {"id": "docs", "weight": 1, "satisfied": True},
            ],
            "remaining_work": ["legal review"],
        },
    )
    feat, e = ev(f, "pilot")
    assert feat.implementation.percent() == 100.0  # technical not reduced
    assert e.disposition == "BUSINESS_READINESS_PENDING"


# -- Scenario 8: scope expansion --------------------------------------------
def test_scenario_8_scope_expansion_does_not_reduce_completed_scope():
    # V1: two in-scope controls, both satisfied -> 100%. A future requirement
    # marked out-of-scope (in_scope: false) must not reduce V1 completion.
    v1 = base_feature(
        implementation={
            "state": "TURNKEY",
            "denominator": "V1 in-scope controls",
            "controls": [
                {"id": "c1", "weight": 1, "satisfied": True},
                {"id": "c2", "weight": 1, "satisfied": True},
                {"id": "v2-future", "weight": 5, "satisfied": False, "in_scope": False},
            ],
            "remaining_work": [],
        }
    )
    feat_v1 = feature_from_dict(v1)
    assert feat_v1.implementation.percent() == 100.0  # deferred req excluded

    # V2: same feature, new denominator, version bumped, requirement now in-scope.
    v2 = base_feature(
        scope={"id": "sample-v2", "version": 2, "title": "Sample V2", "target": "ga"},
        implementation={
            "state": "RUNTIME_INTEGRATED",
            "denominator": "V2 in-scope controls",
            "controls": [
                {"id": "c1", "weight": 1, "satisfied": True},
                {"id": "c2", "weight": 1, "satisfied": True},
                {"id": "v2-future", "weight": 5, "satisfied": False, "in_scope": True},
            ],
            "remaining_work": ["build v2-future"],
        },
    )
    feat_v2 = feature_from_dict(v2)
    assert feat_v2.implementation.percent() < 100.0
    assert feat_v2.scope.version == 2 and feat_v1.scope.version == 1


# -- Scenario 9: intentionally disabled feature -----------------------------
def test_scenario_9_disabled_intentionally():
    f = base_feature(
        release_profiles={"local": {"participation": "disabled_intentionally"}},
    )
    feat, e = ev(f, "local")
    assert e.disposition == "DISABLED_INTENTIONALLY"
    assert e.hard_blockers == []  # not represented as broken


def test_scenario_9_disabled_not_counted_in_profile_coverage():
    disabled = feature_from_dict(
        base_feature(feature_id="disabled-cap", release_profiles={"staging": {"participation": "disabled_intentionally"}})
    )
    active = feature_from_dict(base_feature(feature_id="active-cap"))
    report = evaluate_release_profile("staging", [disabled, active], MODEL)
    assert "disabled-cap" not in report.required_features
    assert "disabled-cap" not in report.experimental_features
    # coverage denominator only counts the active required capability
    assert report.coverage["implementation"]["of"] == 1


# -- Scenario 10: failed credentialed staging test --------------------------
def test_scenario_10_failed_credentialed_staging():
    f = base_feature(
        activation={"state": "NO_EXTERNAL_BLOCKER", "blockers": []},
        environment_evidence={
            "local": {"state": "VERIFIED", "credentialed": False},
            "ci": {"state": "VERIFIED", "credentialed": False},
            "staging": {
                "state": "FAILED",
                "credentialed": True,
                "failure_summary": "connection self-check failed against provider sandbox",
            },
        },
        confidence={"level": "LOW", "evidence_gaps": ["credentialed staging failed"]},
    )
    feat, e = ev(f, "staging")
    assert feat.implementation.percent() == 100.0  # not automatically decreased
    assert feat.environment_evidence["staging"].state == "FAILED"
    assert e.disposition in BLOCKING_DISPOSITIONS
    assert e.disposition not in ELIGIBLE_DISPOSITIONS
    assert feat.environment_evidence["staging"].failure_summary


# -- Percentage rules --------------------------------------------------------
def test_percentage_only_counts_in_scope_controls():
    from scripts.lib.readiness_model import Control

    controls = [
        Control(id="a", weight=1, satisfied=True),
        Control(id="b", weight=1, satisfied=False, in_scope=False),
    ]
    assert completion_percent(controls) == 100.0


def test_empty_controls_are_vacuously_complete():
    assert completion_percent([]) == 100.0
