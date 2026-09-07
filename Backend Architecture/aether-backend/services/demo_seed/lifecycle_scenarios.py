"""Scenario-tenant planner for the end-user lifecycle E2E suites A-F.

This module is the PURE scenario-state layer of the lifecycle staging seeder.
It has NO I/O and NO dependency on any repository / store / config: it maps each
lifecycle suite (A-F, the executable acceptance spec in
``frontend/aether/src/test/e2e/lifecycle-{A,B,C,D,E,F}-*.spec.ts`` +
``lifecycle.harness.ts``) onto the tenant / user / activation / connector state
the suite's starting conditions assert, expressed ONLY against the canonical
stores and field vocabularies the backend actually reads (verified against the
code; no schema is invented here):

* landing decision  -> ``tenant_implementation_plans.status``
  (``services/onboarding``; the FE ``TenantLanding`` routes a non-complete
  status to ``/activation`` and a complete status to the workspace).
* saved intents     -> ``tenant_activations.intents`` (the durable WS-3
  ``ActivationIntent`` tokens the tenant UI saves through
  ``services/activation``).
* connector records -> ``integration_connector_configs`` rows for the BYOD
  ``connector_service`` surface, which is exactly what ``Settings ->
  Integrations`` renders (``/v1/tenant-integrations`` lists ONLY stored rows).
* revoked credential-> ``tenant_credentials.status='revoked'`` (the credential
  platform's authoritative revoked flag, ``shared/credentials``).

Honesty law (mirrors the repo rule: never fake a credential, never fabricate
sync/evidence/readiness):

* NO plan ever carries a credential value, a secret reference, a fabricated
  sync status, or a fabricated evidence row.
* ``tenant_activations.state`` is NEVER seeded as ``complete``: in the backend
  activation machine, ``complete`` requires key minting + a durable Bronze
  first-value row (real evidence). Seeding it here would be a fabricated
  readiness claim. Returning tenants (B-F) instead carry the honest durable
  record the real API itself produces for an authenticated tenant who has
  saved goals: ``state=account_verified`` + their saved ``intents``.
* Connector *record* facts that a seed could only fake (``connected`` from a
  real credential, ``failed``/``degraded`` from a real sync attempt) are
  declared as ``seedable=False`` presences and left to operator-supplied
  provider credentials + live sync evidence (the integration env), which is
  exactly what the E2E runbook treats as reset-seed preconditions.
* Only the genuinely record-fact-false rows are ``seedable=True``: an
  all-defaults ``integration_connector_configs`` row (not enabled, no secret,
  never synced) that honestly renders as "available / not connected" under the
  catalog's Communications group. This is how suite C's comms cohort is made
  visible in ``/v1/tenant-integrations`` (the Settings surface lists only
  stored rows — a provider row absent from the store cannot appear there).
* Suite D's revoked-Google-Ads starting state is NOT fully seedable by this
  slice: the authoritative revoked representation is the real
  ``tenant_credentials.status='revoked'`` flag on an operator-supplied
  previously-configured credential, and the "Needs attention" render
  additionally requires the ad-platform measurement connector record to carry a
  real failed/degraded sync outcome (WS-4 surface). Declaring D "seedable" by
  writing a ``sync_status`` field would be fabricating a sync result, so D's
  connector/credential state is declared operator-bound below.
* Suite E's open mapping review is created by the campaign resolver from REAL
  ambiguous ad sync evidence (``services/campaign/resolver``); a synthetic open
  review row would be fabricated evidence, so it is operator-bound too. The
  canonical campaign the review resolves to is the env-supplied
  ``E2E_CAMPAIGN_UUID`` (gated by the E suite harness).

Each scenario therefore separates two layers explicitly:

1. ``seed`` rows the ``seed-lifecycle`` CLI writes idempotently (tenant + user +
   implementation plan + activation record with saved intents + any genuinely
   record-fact-honest connector rows), and
2. ``operator_steps`` — the credential/evidence/env actions the R3/R4
   integration environment must satisfy so the suite's later journey has real
   data to read. This module never pretends layer (2) is seed code.

Suite meanings (single source mirroring the E2E specs / plan §7):

* A — e-commerce + ads FIRST-TIME tenant. Incomplete activation: no saved
  intents, no connect plan, nothing connected (no connector rows stored). The
  suite itself drives intent selection (sell_online), Shopify connect, Meta Ads
  connect, sync, complete.
* B — returning EXPANSION tenant. Already in the workspace (plan ``live``) with
  commerce connected so Campaign 360 has data; the suite adds Google Ads
  contextually and syncs.
* C — COMMUNICATIONS lifecycle. Activated tenant in the workspace whose
  Settings → Integrations shows the catalog-derived comms cohort as available;
  the suite connects Klaviyo and syncs.
* D — CREDENTIAL RECOVERY. Activated tenant whose previously-connected Google
  Ads credential has been REVOKED; a revoked/degraded integration must never
  render as Ready; reconnect restores health only after evidence.
* E — MAPPING EXCEPTION. Activated tenant with an open/ambiguous mapping review
  and a canonical Aether campaign UUID (E2E_CAMPAIGN_UUID) to resolve it to.
* F — ACTIVATION ROUTE CONVERGENCE + TENANT LANDING. A complete tenant:
  /activate preserves query params onto /activation, /activation renders
  directly, and returning tenants land on their last useful workspace.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Canonical store tokens (real table/store names — verified; never invented).
# ─────────────────────────────────────────────────────────────────────────────

TENANTS_STORE = "tenants"
USERS_STORE = "users"
IMPLEMENTATION_PLANS_STORE = "tenant_implementation_plans"
ACTIVATION_STORE = "tenant_activations"
CONNECTOR_CONFIG_STORE = "integration_connector_configs"
MEASUREMENT_CONNECTOR_STORE = "measurement_connectors"
TENANT_CREDENTIALS_STORE = "tenant_credentials"

# Canonical field names the seeder targets on those stores.
CREDENTIAL_STATUS_FIELD = "status"
CREDENTIAL_STATUS_REVOKED = "revoked"

# Onboarding implementation-plan statuses (services/onboarding ImplementationStatus).
LANDING_COMPLETE_STATUSES: frozenset[str] = frozenset(
    {"live", "value_proven", "expansion_ready"}
)
LANDING_INCOMPLETE_STATUS = "not_started"

# Activation record state vocabulary we seed (services/activation ActivationState).
# ``account_verified`` is the durable base the real ``/v1/activation/status``
# path writes for an authenticated tenant; the E2E seeder uses it for every
# returning tenant so saved intents sit on a real, reachable record.
ACTIVATION_STATE_NOT_STARTED = "not_started"
ACTIVATION_STATE_ACCOUNT_VERIFIED = "account_verified"
# ``complete`` is deliberately never declared by a plan: it requires SDK
# key-minting + a durable Bronze first-value row (evidence the seeder never
# fabricates). Kept as a documented sentinel.
ACTIVATION_STATE_COMPLETE = "complete"

# Canonical ActivationIntent tokens (services/activation planner vocabulary).
ACTIVATION_INTENT_GROW_REVENUE = "grow_revenue"
ACTIVATION_INTENT_RUN_ADVERTISING = "run_advertising"
ACTIVATION_INTENT_ENGAGE_CUSTOMERS = "engage_customers"
VALID_ACTIVATION_INTENTS: frozenset[str] = frozenset(
    {
        ACTIVATION_INTENT_GROW_REVENUE,
        ACTIVATION_INTENT_RUN_ADVERTISING,
        "know_customers",
        ACTIVATION_INTENT_ENGAGE_CUSTOMERS,
        "understand_behavior",
        "grow_community",
        "support_customers",
        "streamline_work",
    }
)

# Provider-family / connector_type tokens (catalog + connector stores).
SHOPIFY = "shopify"
KLAVIYO = "klaviyo"
SENDGRID = "sendgrid"
CUSTOMERIO = "customerio"
MAILCHIMP = "mailchimp"
GOOGLE_ADS = "google_ads"
META_ADS = "meta_ads"

# Feature flags the E2E suites require the backend to run with (config/settings;
# defaults are OFF). The seeder never toggles them; it documents the requirement.
SCENARIO_REQUIRED_FLAGS: tuple[str, ...] = (
    "AETHER_ACTIVATION_ENABLED",
    "AETHER_CONNECTORS_ENABLED",
)

# Suite E's canonical-campaign contract (lifecycle.harness.ts / E spec gate).
CAMPAIGN_UUID_ENV = "E2E_CAMPAIGN_UUID"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario model.
# ─────────────────────────────────────────────────────────────────────────────


class LifecycleSuite(str, enum.Enum):
    """One end-user lifecycle E2E suite (A-F)."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


LIFECYCLE_SUITES: tuple[LifecycleSuite, ...] = tuple(LifecycleSuite)


@dataclass(frozen=True)
class ConnectorPresence:
    """One connector-family state a suite's C1 starting conditions expect.

    ``store`` names the REAL store that holds the row. ``seedable`` is True only
    when the ``seed-lifecycle`` CLI can write the row honestly WITHOUT a
    credential value, a secret ref, or a fabricated sync/evidence outcome (i.e.
    an all-record-fact-false ``integration_connector_configs`` row that renders
    as "available / not connected"). Everything else (credentials, ad-platform
    connector state, revocations, degraded sync) is ``seedable=False`` and
    belongs to the operator/env layer (``why_not_seedable`` states the reason).
    """

    family: str
    store: str
    seedable: bool = False
    c1_expected_state: Optional[str] = None
    marker: str = ""
    why_not_seedable: str = ""

    @property
    def is_revocation_marker(self) -> bool:
        """True when this presence declares a revoked credential representation."""
        return self.marker == f"{CREDENTIAL_STATUS_FIELD}={CREDENTIAL_STATUS_REVOKED}"


@dataclass(frozen=True)
class ScenarioPlan:
    """Declarative seed/state target for one lifecycle E2E suite (pure).

    This is a pure description; applying it to real stores is the
    ``seed-lifecycle`` CLI's job. No field ever holds a credential value.
    """

    suite: LifecycleSuite
    name: str
    summary: str
    # tenant_implementation_plans.status to seed (drives the FE landing decision).
    landing_status: str
    # True when the seeder writes a tenant_activations row at ``activation_state``
    # carrying ``intents``; False leaves the real API to auto-create the record.
    activation_record: bool = False
    # Target tenant_activations.state (honest value only — never `complete`,
    # which would require fabricated Bronze evidence).
    activation_state: str = ACTIVATION_STATE_NOT_STARTED
    # Saved ActivationIntent tokens (canonical vocabulary; durable WS-3 profile
    # fact — genuine tenant goals, not readiness).
    intents: tuple[str, ...] = ()
    # Connector-family rows the suite's C1 state references.
    connector_presence: tuple[ConnectorPresence, ...] = ()
    # True when the E suite requires E2E_CAMPAIGN_UUID + an open review to exist.
    open_review_required: bool = False
    # What remains operator/env-supplied after the CLI seeds (credentials,
    # evidence, syncs, revocations, reviews). The E2E runbook's reset seed must
    # satisfy these before a suite run.
    operator_steps: tuple[str, ...] = ()
    # Feature flags the backend must have ON for the suite to drive connect
    # flows (never toggled by the seeder; documented only).
    required_flags: tuple[str, ...] = field(default=SCENARIO_REQUIRED_FLAGS)

    # ── Derived helpers (pure) ───────────────────────────────────────────────

    @property
    def landing_complete(self) -> bool:
        """True when the seeded plan status routes the tenant to the workspace."""
        return self.landing_status in LANDING_COMPLETE_STATUSES

    @property
    def saved_intents(self) -> list[str]:
        return list(self.intents)

    @property
    def seedable_connectors(self) -> list[ConnectorPresence]:
        """Connector rows the CLI may write honestly (record-fact-false rows)."""
        return [c for c in self.connector_presence if c.seedable]

    @property
    def operator_bound_connectors(self) -> list[ConnectorPresence]:
        """Connector states only the operator/env may realize (no faking)."""
        return [c for c in self.connector_presence if not c.seedable]


# ─────────────────────────────────────────────────────────────────────────────
# Scenario definitions (A-F) — pure, exhaustive.
# ─────────────────────────────────────────────────────────────────────────────

_SCENARIOS: dict[LifecycleSuite, ScenarioPlan] = {
    LifecycleSuite.A: ScenarioPlan(
        suite=LifecycleSuite.A,
        name="ecommerce + ads first-time tenant",
        summary=(
            "Incomplete activation: no saved activation intents, no connect plan, "
            "no stored connector rows, and a not_started implementation plan, so "
            "TenantLanding routes / to /activation. The suite selects a commerce "
            "intent, connects Shopify under Commerce & Revenue, connects Meta Ads "
            "under Advertising, syncs, completes activation, and enters Campaigns "
            "resolved from real sync state."
        ),
        landing_status=LANDING_INCOMPLETE_STATUS,
        activation_record=False,
        activation_state=ACTIVATION_STATE_NOT_STARTED,
        intents=(),
        connector_presence=(),
        operator_steps=(
            "Suite A connects Shopify and Meta Ads ITSELF during the run using "
            "E2E-supplied provider credentials — no pre-seeded connector/credential "
            "is required or seeded.",
            "backend must run with connectors_enabled + activation_enabled ON",
            "each run starts from a reset seed so A1 begins incomplete",
        ),
    ),
    LifecycleSuite.B: ScenarioPlan(
        suite=LifecycleSuite.B,
        name="returning expansion tenant (add advertising)",
        summary=(
            "Returning tenant already in the workspace (implementation plan live) "
            "with commerce connected so Campaign 360 has data. The suite adds "
            "Google Ads through the contextual advertising path, connects with "
            "account selection, syncs, and returns to Campaigns. Activation posture "
            "is the honest durable record (account_verified + grow_revenue intent)."
        ),
        landing_status="live",
        activation_record=True,
        activation_state=ACTIVATION_STATE_ACCOUNT_VERIFIED,
        intents=(ACTIVATION_INTENT_GROW_REVENUE,),
        connector_presence=(
            ConnectorPresence(
                family=SHOPIFY,
                store=CONNECTOR_CONFIG_STORE,
                seedable=False,
                c1_expected_state="connected",
                marker="commerce already connected (Campaign 360 data)",
                why_not_seedable=(
                    "a genuine 'commerce connected' record fact requires a real "
                    "Shopify credential + sync evidence (operator-supplied); writing "
                    "enabled/secret_configured/sync_status by hand would fake it"
                ),
            ),
            ConnectorPresence(
                family=GOOGLE_ADS,
                store=MEASUREMENT_CONNECTOR_STORE,
                seedable=False,
                c1_expected_state="available",
                why_not_seedable=(
                    "Google Ads rows live in the ad-platform measurement store "
                    "(campaign-sources / WS-4 read model), not the BYOD connector "
                    "store, and are created by the ad connect flow with real "
                    "credentials"
                ),
            ),
        ),
        operator_steps=(
            "operator connects Shopify with real credentials + runs a sync so "
            "Campaign 360 has commerce data (sync evidence, not seed data)",
            "suite B connects Google Ads itself during the run",
            "backend must run with connectors_enabled + activation_enabled ON",
        ),
    ),
    LifecycleSuite.C: ScenarioPlan(
        suite=LifecycleSuite.C,
        name="communications lifecycle (Klaviyo)",
        summary=(
            "Activated tenant in the workspace. Its Settings → Integrations "
            "Communications group lists the catalog-derived comms cohort "
            "(Klaviyo + sendgrid/customerio/mailchimp companions) as available — "
            "achieved by seeding the cohort's all-defaults (never enabled, no "
            "secret, never synced) BYOD connector rows, which is the ONLY honest "
            "way for /v1/tenant-integrations (stored rows only) to show them. The "
            "suite connects Klaviyo, syncs, and reaches comms-sourced campaign "
            "facts in Campaign 360."
        ),
        landing_status="live",
        activation_record=True,
        activation_state=ACTIVATION_STATE_ACCOUNT_VERIFIED,
        intents=(ACTIVATION_INTENT_ENGAGE_CUSTOMERS,),
        connector_presence=(
            # All record facts false: renders as available / not connected under
            # the Communications group. connector_type values are the catalog's
            # comms.* family tokens, all valid ConnectorConfig BYOD types.
            ConnectorPresence(
                family=KLAVIYO,
                store=CONNECTOR_CONFIG_STORE,
                seedable=True,
                c1_expected_state="not_connected",
            ),
            ConnectorPresence(
                family=SENDGRID,
                store=CONNECTOR_CONFIG_STORE,
                seedable=True,
                c1_expected_state="not_connected",
            ),
            ConnectorPresence(
                family=CUSTOMERIO,
                store=CONNECTOR_CONFIG_STORE,
                seedable=True,
                c1_expected_state="not_connected",
            ),
            ConnectorPresence(
                family=MAILCHIMP,
                store=CONNECTOR_CONFIG_STORE,
                seedable=True,
                c1_expected_state="not_connected",
            ),
        ),
        operator_steps=(
            "suite C connects Klaviyo itself with the E2E-supplied credential + "
            "a real sync during the run",
            "comms-sourced campaign facts in Campaign 360 are sync evidence, "
            "not seed data",
            "backend must run with connectors_enabled + activation_enabled ON",
        ),
    ),
    LifecycleSuite.D: ScenarioPlan(
        suite=LifecycleSuite.D,
        name="credential recovery (revoked Google Ads)",
        summary=(
            "Activated tenant in the workspace whose previously-connected Google "
            "Ads integration has a REVOKED credential. The revoked/degraded "
            "integration must render 'Needs attention' (never Ready), impact is "
            "disclosed, and reconnect restores health only from live credential "
            "evidence."
        ),
        landing_status="live",
        activation_record=True,
        activation_state=ACTIVATION_STATE_ACCOUNT_VERIFIED,
        intents=(ACTIVATION_INTENT_GROW_REVENUE, ACTIVATION_INTENT_RUN_ADVERTISING),
        connector_presence=(
            ConnectorPresence(
                family=GOOGLE_ADS,
                store=TENANT_CREDENTIALS_STORE,
                seedable=False,
                c1_expected_state="needs_attention",
                marker=f"{CREDENTIAL_STATUS_FIELD}={CREDENTIAL_STATUS_REVOKED}",
                why_not_seedable=(
                    "the ONLY honest revoked representation is the real "
                    "tenant_credentials.status='revoked' flag on an operator-"
                    "supplied previously-configured credential; rendering "
                    "'Needs attention' additionally requires the ad-platform "
                    "measurement connector record (WS-4 surface) to carry a real "
                    "failed/degraded sync outcome — this slice refuses to fake a "
                    "credential or a sync field"
                ),
            ),
        ),
        operator_steps=(
            "operator connects Google Ads with real credentials, revokes that "
            "credential (tenant_credentials.status='revoked' + revoked_at), and "
            "lets the real sync/revalidation path surface needs_attention before "
            "the run",
            "backend must run with connectors_enabled + activation_enabled ON",
        ),
    ),
    LifecycleSuite.E: ScenarioPlan(
        suite=LifecycleSuite.E,
        name="mapping exception (ambiguous ad campaign)",
        summary=(
            "Activated tenant in the workspace whose environment carries an "
            "open/ambiguous mapping review and a canonical Aether campaign UUID "
            "(E2E_CAMPAIGN_UUID) to resolve it to. The suite drives the real "
            "exception -> readiness review -> Mapping Review -> resolution -> "
            "canonical-identity flow."
        ),
        landing_status="live",
        activation_record=True,
        activation_state=ACTIVATION_STATE_ACCOUNT_VERIFIED,
        intents=(ACTIVATION_INTENT_RUN_ADVERTISING,),
        connector_presence=(),
        open_review_required=True,
        operator_steps=(
            "an open campaign_resolution_reviews row must exist — it is created "
            "by the campaign resolver from REAL ambiguous ad sync evidence "
            "(services/campaign/resolver), never seeded as fabricated evidence",
            f"{CAMPAIGN_UUID_ENV} must name a canonical campaign that exists for "
            "the tenant (the suite gate skips without it)",
            "backend must run with connectors_enabled + activation_enabled ON",
        ),
    ),
    LifecycleSuite.F: ScenarioPlan(
        suite=LifecycleSuite.F,
        name="activation route convergence + tenant landing",
        summary=(
            "A COMPLETE tenant (implementation plan live): /activate is a "
            "query-preserving alias onto /activation, /activation renders "
            "directly (no redirect loop), and a returning complete tenant is "
            "restored to their last useful workspace rather than dropped on Home "
            "or /activation."
        ),
        landing_status="live",
        activation_record=True,
        activation_state=ACTIVATION_STATE_ACCOUNT_VERIFIED,
        intents=(),
        connector_presence=(),
        operator_steps=(
            "F's tenant must be seeded complete so the F3 landing decision is "
            "the last-workspace leg (the test seeds the browser "
            "aether:last-workspace:<email> localStorage key itself)",
            "backend must run with connectors_enabled + activation_enabled ON",
        ),
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Public pure API.
# ─────────────────────────────────────────────────────────────────────────────


def scenario_state(suite: str | LifecycleSuite) -> ScenarioPlan:
    """The declarative ScenarioPlan for one lifecycle suite (A-F).

    Raises ``KeyError``/``ValueError`` for anything outside A-F.
    """
    key = suite if isinstance(suite, LifecycleSuite) else LifecycleSuite(suite.upper())
    return _SCENARIOS[key]


def all_scenarios() -> tuple[ScenarioPlan, ...]:
    """Every suite plan in canonical order (A-F)."""
    return tuple(_SCENARIOS[s] for s in LIFECYCLE_SUITES)


def resolve_suite_from_email(email: str) -> Optional[LifecycleSuite]:
    """Map a conventional suite-tenant email onto its LifecycleSuite.

    Recognizes (case-insensitively) a local part that STARTS with ``lifecycle-``
    followed by a suite letter (``lifecycle-b@example.com``), or that ENDS with
    ``-<letter>`` (``tenant-b@example.com``). Returns None for any email that
    does not identify a lifecycle suite tenant. This is a pure helper for
    tooling/harness code that holds only an email; the ``seed-lifecycle`` CLI
    itself iterates the known ``E2E_TENANT_EMAIL_<SUITE>`` env vars instead.
    """
    if not email:
        return None
    local = email.split("@", 1)[0].strip().lower()
    if not local:
        return None
    lowered = local.lower()
    candidate: Optional[str] = None
    prefix = "lifecycle-"
    if lowered.startswith(prefix):
        tail = lowered[len(prefix):]
        if len(tail) >= 1 and tail[0] in "abcdef":
            candidate = tail[0]
    if candidate is None and len(local) >= 2 and local[-2] == "-" and local[-1] in "abcdef":
        candidate = local[-1]
    if candidate is None:
        return None
    return LifecycleSuite(candidate.upper())


def scenario_plan_for_email(email: str) -> Optional[ScenarioPlan]:
    """ScenarioPlan for a conventional suite-tenant email, or None."""
    suite = resolve_suite_from_email(email)
    return scenario_state(suite) if suite is not None else None


# Suite-credential env-var contract (lifecycle.harness.ts lifecycleSuiteCredentials).
def tenant_email_env(suite: str) -> str:
    """Env var holding suite tenant email (``E2E_TENANT_EMAIL_<SUITE>``)."""
    return f"E2E_TENANT_EMAIL_{suite.upper()}"


def tenant_password_env(suite: str) -> str:
    """Env var holding suite tenant password (``E2E_TENANT_PASSWORD_<SUITE>``)."""
    return f"E2E_TENANT_PASSWORD_{suite.upper()}"


def validate_scenario_plan(plan: ScenarioPlan) -> None:
    """Assert a plan's declared vocabulary is canonical (pure integrity gate).

    Used by tests (and defensively by the CLI before it applies a plan) so a
    typo'd intent token, activation state, store token, or landing status is
    caught against the real vocabulary instead of silently seeding a wrong row.
    """
    unknown_intents = [t for t in plan.intents if t not in VALID_ACTIVATION_INTENTS]
    if unknown_intents:
        raise ValueError(f"{plan.suite}: unknown activation intent(s): {unknown_intents}")
    if plan.landing_status not in LANDING_COMPLETE_STATUSES and plan.landing_status != LANDING_INCOMPLETE_STATUS:
        raise ValueError(f"{plan.suite}: unknown landing status {plan.landing_status!r}")
    if plan.activation_record:
        if plan.activation_state not in {
            ACTIVATION_STATE_NOT_STARTED,
            ACTIVATION_STATE_ACCOUNT_VERIFIED,
        }:
            raise ValueError(
                f"{plan.suite}: refusing to seed activation state "
                f"{plan.activation_state!r}; the E2E seeder never writes "
                f"'{ACTIVATION_STATE_COMPLETE}' (it would require fabricated "
                "SDK key/first-value evidence) — use not_started or account_verified"
            )
    else:
        if plan.intents:
            raise ValueError(
                f"{plan.suite}: activation_record is False but intents are "
                "declared — saved intents need a durable activation record"
            )
    allowed_stores = {
        TENANTS_STORE,
        USERS_STORE,
        IMPLEMENTATION_PLANS_STORE,
        ACTIVATION_STORE,
        CONNECTOR_CONFIG_STORE,
        MEASUREMENT_CONNECTOR_STORE,
        TENANT_CREDENTIALS_STORE,
    }
    for presence in plan.connector_presence:
        if presence.store not in allowed_stores:
            raise ValueError(f"{plan.suite}: unknown connector store {presence.store!r}")
        if presence.seedable and presence.store != CONNECTOR_CONFIG_STORE:
            raise ValueError(
                f"{plan.suite}: only record-fact-false {CONNECTOR_CONFIG_STORE} "
                f"rows are seedable; {presence.family} targets {presence.store}"
            )


__all__ = [
    "ACTIVATION_INTENT_ENGAGE_CUSTOMERS",
    "ACTIVATION_INTENT_GROW_REVENUE",
    "ACTIVATION_INTENT_RUN_ADVERTISING",
    "ACTIVATION_STATE_ACCOUNT_VERIFIED",
    "ACTIVATION_STATE_COMPLETE",
    "ACTIVATION_STATE_NOT_STARTED",
    "ACTIVATION_STORE",
    "CAMPAIGN_UUID_ENV",
    "CONNECTOR_CONFIG_STORE",
    "CREDENTIAL_STATUS_FIELD",
    "CREDENTIAL_STATUS_REVOKED",
    "ConnectorPresence",
    "IMPLEMENTATION_PLANS_STORE",
    "LANDING_COMPLETE_STATUSES",
    "LANDING_INCOMPLETE_STATUS",
    "LIFECYCLE_SUITES",
    "LifecycleSuite",
    "MEASUREMENT_CONNECTOR_STORE",
    "SCENARIO_REQUIRED_FLAGS",
    "ScenarioPlan",
    "SHOPIFY",
    "TENANTS_STORE",
    "TENANT_CREDENTIALS_STORE",
    "USERS_STORE",
    "VALID_ACTIVATION_INTENTS",
    "all_scenarios",
    "resolve_suite_from_email",
    "scenario_plan_for_email",
    "scenario_state",
    "tenant_email_env",
    "tenant_password_env",
    "validate_scenario_plan",
]
