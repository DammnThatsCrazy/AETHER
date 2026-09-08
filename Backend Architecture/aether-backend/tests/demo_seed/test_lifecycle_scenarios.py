"""DB-free tests for the pure lifecycle scenario planner (C4).

These assert the A-F scenario plans against the state the FE lifecycle E2E
harness/specs actually require, and pin the honesty invariants the whole
lifecycle staging slice is built around:

* never an activation state of ``complete`` (that would fabricate SDK
  key/first-value evidence),
* no seedable connector row outside the BYOD ``integration_connector_configs``
  store, and no ad-platform family declared seedable in it,
* suite D's revoked Google Ads is declared against the real
  ``tenant_credentials.status='revoked'`` representation and is NOT seedable,
* no planner I/O — pure vocabulary, importable with no repository/store/config.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from services.demo_seed.lifecycle_scenarios import (
    ACTIVATION_STATE_ACCOUNT_VERIFIED,
    ACTIVATION_STATE_COMPLETE,
    ACTIVATION_STATE_NOT_STARTED,
    CAMPAIGN_UUID_ENV,
    CONNECTOR_CONFIG_STORE,
    GOOGLE_ADS,
    KLAVIYO,
    LANDING_COMPLETE_STATUSES,
    LANDING_INCOMPLETE_STATUS,
    LIFECYCLE_SUITES,
    LifecycleSuite,
    MEASUREMENT_CONNECTOR_STORE,
    SCENARIO_REQUIRED_FLAGS,
    SHOPIFY,
    TENANT_CREDENTIALS_STORE,
    VALID_ACTIVATION_INTENTS,
    all_scenarios,
    resolve_suite_from_email,
    scenario_plan_for_email,
    scenario_state,
    tenant_email_env,
    tenant_password_env,
    validate_scenario_plan,
)

ALL_SUITES = list(LIFECYCLE_SUITES)


def test_all_suites_present_and_canonical_order() -> None:
    plans = all_scenarios()
    assert [p.suite for p in plans] == ALL_SUITES
    assert len(plans) == 6
    for plan in plans:
        validate_scenario_plan(plan)  # vocabulary gate passes for every plan


def test_scenario_state_access_is_exhaustive() -> None:
    for suite in ALL_SUITES:
        by_enum = scenario_state(suite)
        by_str = scenario_state(suite.value)
        by_lower = scenario_state(suite.value.lower())
        assert by_enum is by_str and by_enum is by_lower
    with pytest.raises((KeyError, ValueError)):
        scenario_state("Z")


# ── Suite A: e-commerce + ads FIRST-TIME tenant ──────────────────────────────


def test_A_first_time_tenant_is_incomplete() -> None:
    plan = scenario_state("A")
    assert plan.name == "ecommerce + ads first-time tenant"
    # An incomplete tenant must route root to /activation (TenantLanding), so the
    # seeded implementation-plan status is not_started and NOT landing-complete.
    assert plan.landing_status == LANDING_INCOMPLETE_STATUS
    assert not plan.landing_complete
    # Fresh tenant: no saved intents, no activation record seeded (the real API
    # auto-creates it when the run starts), no stored connector rows.
    assert plan.activation_record is False
    assert plan.intents == ()
    assert plan.connector_presence == ()
    assert plan.seedable_connectors == []
    assert plan.operator_bound_connectors == []
    assert plan.operator_steps  # documents the env/run reset preconditions


# ── Suite B: returning expansion tenant (commerce connected) ─────────────────


def test_B_returning_expansion_landing_complete_and_intents() -> None:
    plan = scenario_state("B")
    assert plan.landing_complete is True
    assert plan.landing_status in LANDING_COMPLETE_STATUSES
    # B's tenant already saved the grow_revenue goal (returns to expand into ads).
    assert plan.activation_record is True
    assert plan.intents == ("grow_revenue",)
    assert all(t in VALID_ACTIVATION_INTENTS for t in plan.intents)


def test_B_commerce_connected_is_operator_bound_not_seedable() -> None:
    plan = scenario_state("B")
    by_family = {p.family: p for p in plan.connector_presence}
    # Commerce-connected is an evidence fact (credential + sync), never a seed row.
    shopify = by_family[SHOPIFY]
    assert shopify.store == CONNECTOR_CONFIG_STORE
    assert shopify.seedable is False
    assert shopify.c1_expected_state == "connected"
    assert "credential" in shopify.why_not_seedable.lower()
    # Google Ads lives in the ad-platform measurement surface — not the BYOD
    # connector store — and requires a real ad-connect credential.
    google = by_family[GOOGLE_ADS]
    assert google.store == MEASUREMENT_CONNECTOR_STORE
    assert google.seedable is False
    # No B row is a stored-record seed; the C1 commerce/ad state is the runbook's.
    assert plan.seedable_connectors == []
    assert len(plan.operator_bound_connectors) == 2


# ── Suite C: communications lifecycle (Klaviyo cohort) ───────────────────────


def test_C_comms_cohort_is_the_only_seedable_connector_rows() -> None:
    plan = scenario_state("C")
    assert plan.landing_complete is True
    assert plan.intents == ("engage_customers",)
    families = {p.family for p in plan.connector_presence}
    assert families == {"klaviyo", "sendgrid", "customerio", "mailchimp"}
    for presence in plan.connector_presence:
        # Klaviyo + the comms cohort render under Settings→Integrations ONLY via
        # stored /v1/tenant-integrations rows; they are seeded as all-record-fact-
        # false BYOD rows (available / not_connected) — never enabled, no secret,
        # never synced, no ad-platform family.
        assert presence.seedable is True
        assert presence.store == CONNECTOR_CONFIG_STORE
        assert presence.c1_expected_state == "not_connected"
        assert presence.family != GOOGLE_ADS
    assert {p.family for p in plan.seedable_connectors} == families
    assert plan.operator_bound_connectors == []


def test_C_klaviyo_is_present_and_connectable_at_c1() -> None:
    plan = scenario_state("C")
    klaviyo = next(p for p in plan.connector_presence if p.family == KLAVIYO)
    assert klaviyo.seedable is True
    assert klaviyo.c1_expected_state == "not_connected"


# ── Suite D: credential recovery (revoked Google Ads) ────────────────────────


def test_D_carries_revoked_google_ads_marker() -> None:
    plan = scenario_state("D")
    assert plan.landing_complete is True
    assert plan.intents == ("grow_revenue", "run_advertising")
    revoked = [p for p in plan.connector_presence if p.is_revocation_marker]
    assert len(revoked) == 1
    google = revoked[0]
    assert google.family == GOOGLE_ADS
    # The only honest revoked representation is the REAL tenant_credentials
    # status='revoked' flag — declared, but NOT writable by this seed slice.
    assert google.store == TENANT_CREDENTIALS_STORE
    assert google.seedable is False
    assert google.c1_expected_state == "needs_attention"
    assert "revoked" in google.marker
    assert google.why_not_seedable


def test_D_never_declares_a_seedable_revocation() -> None:
    plan = scenario_state("D")
    # No stored connector-config row could carry 'revoked'; the FE 'Needs
    # attention' render requires real credential + sync evidence (WS-4).
    assert plan.seedable_connectors == []
    assert all(not p.seedable for p in plan.connector_presence)


# ── Suite E: mapping exception (ambiguous ad campaign) ───────────────────────


def test_E_mapping_exception_requires_open_review_and_campaign_uuid() -> None:
    plan = scenario_state("E")
    assert plan.landing_complete is True
    assert plan.activation_record is True
    assert plan.intents == ("run_advertising",)
    assert plan.open_review_required is True
    joined_steps = "\n".join(plan.operator_steps).lower()
    assert CAMPAIGN_UUID_ENV.lower() in joined_steps
    assert "review" in joined_steps


# ── Suite F: activation route convergence + tenant landing ───────────────────


def test_F_complete_tenant_lands_in_workspace() -> None:
    plan = scenario_state("F")
    assert plan.name == "activation route convergence + tenant landing"
    assert plan.landing_status == "live"
    assert plan.landing_complete is True
    # F is the completed tenant; its scenario owns no connector or review rows.
    assert plan.activation_record is True
    assert plan.intents == ()
    assert plan.connector_presence == ()


# ── Cross-suite honesty invariants ───────────────────────────────────────────


def test_no_plan_fabricates_completed_activation() -> None:
    for plan in all_scenarios():
        if plan.activation_record:
            # Never 'complete': reaching it needs SDK key-minting + a durable
            # Bronze first-value row (real evidence this seeder does not fake).
            assert plan.activation_state != ACTIVATION_STATE_COMPLETE
            assert plan.activation_state in {
                ACTIVATION_STATE_NOT_STARTED,
                ACTIVATION_STATE_ACCOUNT_VERIFIED,
            }
        else:
            # A suite with no activation record may not smuggle saved intents.
            assert plan.intents == ()


def test_every_returning_tenant_has_honest_durable_activation_record() -> None:
    for suite in ("B", "C", "D", "E", "F"):
        plan = scenario_state(suite)
        assert plan.activation_record is True
        assert plan.activation_state == ACTIVATION_STATE_ACCOUNT_VERIFIED


def test_only_record_fact_false_byod_rows_are_seedable() -> None:
    for plan in all_scenarios():
        for presence in plan.seedable_connectors:
            assert presence.store == CONNECTOR_CONFIG_STORE
            assert presence.family not in {GOOGLE_ADS, "meta_ads"}
        for presence in plan.connector_presence:
            if presence.store != CONNECTOR_CONFIG_STORE:
                assert presence.seedable is False


def test_scenarios_document_env_operator_steps_honestly() -> None:
    # Every suite states what remains env/credential/evidence-bound after seed —
    # none pretends the CLI alone realizes the full journey.
    for plan in all_scenarios():
        assert plan.operator_steps


def test_required_feature_flags_documented_but_never_seeded() -> None:
    for plan in all_scenarios():
        assert "AETHER_CONNECTORS_ENABLED" in plan.required_flags
        assert "AETHER_ACTIVATION_ENABLED" in plan.required_flags
    assert set(SCENARIO_REQUIRED_FLAGS) == {
        "AETHER_CONNECTORS_ENABLED",
        "AETHER_ACTIVATION_ENABLED",
    }


def test_validate_rejects_fabricated_complete_state() -> None:
    plan = replace(scenario_state("B"), activation_state=ACTIVATION_STATE_COMPLETE)
    with pytest.raises(ValueError):
        validate_scenario_plan(plan)


def test_validate_rejects_noncanonical_intent_token() -> None:
    plan = replace(scenario_state("B"), intents=("sell_online",))
    with pytest.raises(ValueError):
        validate_scenario_plan(plan)


def test_validate_rejects_seedable_row_outside_byod_store() -> None:
    from services.demo_seed.lifecycle_scenarios import ConnectorPresence

    plan = replace(
        scenario_state("C"),
        connector_presence=(
            ConnectorPresence(
                family=GOOGLE_ADS,
                store=TENANT_CREDENTIALS_STORE,
                seedable=True,
            ),
        ),
    )
    with pytest.raises(ValueError):
        validate_scenario_plan(plan)


# ── Pure email/env helpers ───────────────────────────────────────────────────


def test_resolve_suite_from_email_conventions() -> None:
    assert resolve_suite_from_email("lifecycle-b@example.com") == LifecycleSuite.B
    assert resolve_suite_from_email("Lifecycle-C@example.com") == LifecycleSuite.C
    assert resolve_suite_from_email("tenant-d@example.com") == LifecycleSuite.D
    assert resolve_suite_from_email("x") is None
    assert resolve_suite_from_email("") is None
    assert resolve_suite_from_email("lifecycle-x@example.com") is None


def test_scenario_plan_for_email_matches_suite() -> None:
    assert scenario_plan_for_email("lifecycle-e@example.com").suite == LifecycleSuite.E  # type: ignore[union-attr]
    assert scenario_plan_for_email("not-a-tenant@example.com") is None


def test_suite_env_var_names() -> None:
    assert tenant_email_env("a") == "E2E_TENANT_EMAIL_A"
    assert tenant_email_env("F") == "E2E_TENANT_EMAIL_F"
    assert tenant_password_env("B") == "E2E_TENANT_PASSWORD_B"
    assert CAMPAIGN_UUID_ENV == "E2E_CAMPAIGN_UUID"
