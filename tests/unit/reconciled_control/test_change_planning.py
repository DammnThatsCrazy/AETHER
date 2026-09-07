"""Phase-1 planning engine tests (blueprint §32 steps 12-15, §33/§34/§35/§39).

Covers the remediation registry (drift type x integration kind -> action),
candidate ChangeSet generation, control-topology blast radius, the §39 risk
classification rules table, §32-15 automation authority, the §35 concurrency
guard ("never apply a stale ChangeSet"), and the fail-closed Phase-1 §34
transitions (nothing may move a plan toward an execution status).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.managed_integrations.change_planning import (
    ControlTopologyNode,
    RiskInputs,
    assess_risk,
    automation_authority,
    build_plan,
    classify_risk,
    compute_blast_radius,
    remediation_action,
    validate_guards,
    with_status,
)
from services.managed_integrations.contracts import (
    BlastRadiusView,
    ChangeSetPlanView,
    DriftRecord,
)

NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)

DEFAULT_BLAST = BlastRadiusView(
    integration_count=1, tenant_count=1, environment_count=1
)


def _drift(drift_type: str, *, detail: str = "evidence", mi: str = "mi-1") -> DriftRecord:
    return DriftRecord(
        drift_id=f"rcdr_{drift_type[:4]}",
        managed_integration_ref=mi,
        desired_state_ref="rcds_mi-1",
        observed_state_ref="rcobs_mi-1",
        drift_type=drift_type,
        detail=detail,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _plan_kwargs(**overrides) -> dict:
    kwargs = dict(
        managed_integration_ref="mi-1",
        tenant_id="tenant-a",
        environment_id="env-1",
        desired_revision="1",
        observed_revision="rcobs_mi-1",
        reconcile_sequence="seq-7",
        drift=[_drift("version_drift")],
        initiator="reconciler",
        now=NOW,
    )
    kwargs.update(overrides)
    return kwargs


# ── remediation registry (drift type x integration kind) ─────────────────────

def test_sdk_version_drift_remediation_is_repository_upgrade() -> None:
    for kind in (
        "sdk_web", "sdk_ios", "sdk_android", "sdk_react_native",
        "sdk_desktop", "sdk_node", "sdk_python", "sdk_rust", "sdk_other",
    ):
        assert remediation_action("version_drift", kind) == "repository_upgrade"


def test_managed_runtime_version_drift_remediation() -> None:
    assert (
        remediation_action("version_drift", "connector_aether_hosted")
        == "managed_connector_change"
    )
    assert (
        remediation_action("version_drift", "provider_runtime_connection")
        == "provider_runtime_change"
    )


def test_capability_drift_maps_like_version_drift() -> None:
    assert remediation_action("capability_drift", "sdk_node") == "repository_upgrade"
    assert (
        remediation_action("capability_drift", "connector_aether_hosted")
        == "managed_connector_change"
    )


def test_identity_and_health_drift_surface_do_not_mutate() -> None:
    # CP-09: identity mismatch and health facts are review/action, never silent
    # mutations. Both map to the notification action only.
    assert remediation_action("fleet_identity_drift", "sdk_web") == "notification_action"
    assert remediation_action("health_drift", "sdk_web") == "notification_action"
    assert remediation_action("health_drift", "connector_customer_hosted") == (
        "notification_action"
    )


def test_schema_drift_has_no_deterministic_phase1_remediation() -> None:
    # Needs the §38 schema -> mapping compiler (a later phase); never fabricated.
    assert remediation_action("schema_drift", "sdk_web") is None
    assert remediation_action("schema_drift", "connector_aether_hosted") is None


def test_customer_hosted_runtime_is_not_olympus_pushable() -> None:
    # §30: no hidden promise Olympus can rewrite a customer-controlled binary.
    assert remediation_action("version_drift", "connector_customer_hosted") is None
    assert remediation_action("version_drift", "webhook") is None


# ── candidate ChangeSet generation (§32 step 12) ─────────────────────────────

def test_build_plan_from_sdk_version_drift() -> None:
    plan = build_plan(**_plan_kwargs())
    assert plan is not None
    assert plan.status == "draft"
    assert plan.tenant_id == "tenant-a"
    assert plan.environment_id == "env-1"
    assert plan.integration_scope == ["mi-1"]
    assert plan.desired_revision == "1"
    assert plan.observed_revision == "rcobs_mi-1"
    assert plan.reconcile_sequence == "seq-7"
    assert plan.initiator == "reconciler"
    assert len(plan.changes) == 1
    assert plan.changes[0].action == "repository_upgrade"
    assert plan.changes[0].target_ref == "mi-1"
    assert plan.risk.risk_class == "R1"
    assert plan.risk.automation_allowed is True
    assert "gate:simulation" in plan.risk.explanation_refs
    assert plan.blast_radius.integration_count == 1


def test_build_plan_is_idempotent_for_the_same_reconcile() -> None:
    first = build_plan(**_plan_kwargs())
    second = build_plan(**_plan_kwargs())
    assert first is not None and second is not None
    assert first.changeset_id != second.changeset_id  # fresh candidate
    assert first.idempotency_key == second.idempotency_key  # same reconcile


def test_schema_only_drift_yields_no_plan() -> None:
    plan = build_plan(**_plan_kwargs(drift=[_drift("schema_drift")]))
    assert plan is None


def test_mixed_remediable_and_unremediable_drift_plans_only_the_remediable() -> None:
    plan = build_plan(
        **_plan_kwargs(
            drift=[_drift("version_drift"), _drift("schema_drift")]
        )
    )
    assert plan is not None
    assert [c.action for c in plan.changes] == ["repository_upgrade"]
    # Reason records the honest count: 1 of 2 actionable drifts is plan-able;
    # the schema drift is surfaced, not silently skipped.
    assert plan.reason == (
        "candidate plan from 1/2 actionable drift (version_drift); drift "
        "without a deterministic remediation is surfaced as review/action, "
        "not silently skipped"
    )


def test_health_notification_plan_is_trivial() -> None:
    plan = build_plan(**_plan_kwargs(drift=[_drift("health_drift")]))
    assert plan is not None
    assert plan.changes[0].action == "notification_action"
    assert plan.risk.risk_class == "R0"
    assert plan.risk.automation_allowed is True


# ── §32-13 control-topology blast radius ─────────────────────────────────────

def test_compute_blast_radius_aggregates_distinct_counts() -> None:
    nodes = [
        ControlTopologyNode("mi-a", "tenant-a", "env-1"),
        ControlTopologyNode("mi-b", "tenant-a", "env-1", source_origin="olympus"),
        ControlTopologyNode("mi-c", "tenant-b", "env-2"),
    ]
    br = compute_blast_radius(nodes, ["mapping_drift", "version_drift"])
    assert br.integration_count == 3
    assert br.tenant_count == 2
    assert br.environment_count == 2
    assert br.source_origins == ["olympus", "tenant"]
    assert br.actionable_drift_types == ["mapping_drift", "version_drift"]


def test_compute_blast_radius_empty_scope() -> None:
    br = compute_blast_radius([], [])
    assert br.integration_count == 0
    assert br.tenant_count == 0
    assert br.environment_count == 0


def test_build_plan_default_single_node_scope() -> None:
    plan = build_plan(**{**_plan_kwargs(), "source_origin": "olympus"})
    assert plan is not None
    assert plan.blast_radius.tenant_count == 1
    assert plan.blast_radius.source_origins == ["olympus"]


# ── §39 risk classification rules table ──────────────────────────────────────

def _risk(**overrides) -> RiskInputs:
    kwargs = dict(blast_radius=DEFAULT_BLAST)
    kwargs.update(overrides)
    return RiskInputs(**kwargs)


@pytest.mark.parametrize(
    ("inputs", "expected", "token"),
    [
        (_risk(), "R0", "trivial"),
        (_risk(semantic_impact="behavioral"), "R1", "behavioral-or-uncertainty"),
        (
            _risk(semantic_impact="behavioral", fleet_health="degraded"),
            "R2",
            "fleet-degraded",
        ),
        (_risk(semantic_impact="data"), "R2", "data-semantics"),
        (_risk(sensitive_data_impact="credential"), "R3", "sensitive-data"),
        (
            _risk(
                blast_radius=BlastRadiusView(
                    integration_count=2, tenant_count=2, environment_count=2
                )
            ),
            "R3",
            "cross-tenant",
        ),
        (_risk(scope_expansion=True), "R4", "scope-expansion"),
        (_risk(destructive=True), "R5", "destructive"),
        (
            _risk(semantic_impact="behavioral", tenant_criticality="high"),
            "R2",
            "high-criticality",
        ),
    ],
)
def test_classify_risk_rules_table(
    inputs: RiskInputs, expected: str, token: str
) -> None:
    klass, refs = classify_risk(inputs)
    assert klass == expected
    assert any(token in ref for ref in refs)


def test_classify_risk_security_emergency_is_not_derivable() -> None:
    # The security-emergency class is declared by the security authority, never
    # derived from ordinary inputs.
    klass, _refs = classify_risk(_risk(destructive=True))
    assert klass == "R5"


# ── §32-15 automation authority ──────────────────────────────────────────────

@pytest.mark.parametrize(
    ("risk_class", "allowed", "token"),
    [
        ("R0", True, None),
        ("R1", True, "gate:simulation"),
        ("R2", True, "gate:canary"),
        ("R3", False, "approval:olympus_operator"),
        ("R4", False, "approval:tenant_owner"),
        ("R5", False, "approval:governed"),
        ("security_emergency", False, "approval:olympus_security"),
    ],
)
def test_automation_authority_table(
    risk_class: str, allowed: bool, token: str | None
) -> None:
    auto_allowed, tokens = automation_authority(risk_class)  # type: ignore[arg-type]
    assert auto_allowed is allowed
    if token is not None:
        assert token in tokens


def test_security_emergency_authorized_by_olympus_security() -> None:
    unauth = automation_authority("security_emergency")  # type: ignore[arg-type]
    assert unauth == (False, ["approval:olympus_security"])
    auth = automation_authority(
        "security_emergency", security_emergency_authorized=True  # type: ignore[arg-type]
    )
    assert auth == (True, [])


def test_assess_risk_override_class() -> None:
    view = assess_risk(_risk(), security_emergency=True)
    assert view.risk_class == "security_emergency"
    assert view.automation_allowed is False
    assert "approval:olympus_security" in view.required_approval_refs


def test_assess_risk_r5_requires_governed_approval() -> None:
    view = assess_risk(_risk(destructive=True))
    assert view.risk_class == "R5"
    assert view.automation_allowed is False
    assert view.required_approval_refs == ["approval:governed"]


# ── §35 concurrency + idempotency guard ──────────────────────────────────────

def _plan() -> ChangeSetPlanView:
    plan = build_plan(**_plan_kwargs())
    assert plan is not None
    return plan


def test_guards_pass_when_revisions_are_current() -> None:
    verdict = validate_guards(
        _plan(), current_desired_revision="1", current_observed_revision="rcobs_mi-1"
    )
    assert verdict.ok is True
    assert verdict.reason is None


def test_guard_fails_when_desired_revision_advanced() -> None:
    verdict = validate_guards(
        _plan(), current_desired_revision="2", current_observed_revision="rcobs_mi-1"
    )
    assert verdict.ok is False
    assert "desired_revision" in (verdict.reason or "")


def test_guard_fails_when_observed_state_changed() -> None:
    verdict = validate_guards(
        _plan(), current_desired_revision="1", current_observed_revision="rcobs_mi-1-v2"
    )
    assert verdict.ok is False
    assert "observed" in (verdict.reason or "")


# ── Phase-1 §34 transitions (illegal transitions fail closed) ───────────────

def test_draft_promotes_to_planned() -> None:
    promoted = with_status(_plan(), "planned", now=NOW)
    assert promoted.status == "planned"
    assert promoted.superseded_at is None


def test_planned_supersedes_and_stamps_time() -> None:
    plan = with_status(_plan(), "planned", now=NOW)
    superseded = with_status(plan, "superseded", now=NOW)
    assert superseded.status == "superseded"
    assert superseded.superseded_at == NOW


def test_draft_can_be_cancelled_without_execution() -> None:
    cancelled = with_status(_plan(), "cancelled", now=NOW)
    assert cancelled.status == "cancelled"


def test_illegal_execution_transition_raises() -> None:
    plan = with_status(_plan(), "planned", now=NOW)
    with pytest.raises(ValueError, match="illegal"):
        with_status(plan, "ready", now=NOW)
    with pytest.raises(ValueError, match="illegal"):
        with_status(plan, "committed", now=NOW)


def test_terminal_plan_cannot_transition() -> None:
    superseded = with_status(_plan(), "superseded", now=NOW)
    with pytest.raises(ValueError, match="illegal"):
        with_status(superseded, "planned", now=NOW)
