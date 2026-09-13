"""Additive lifecycle-scenario tenant seeder (C3) for the A-F E2E suites.

Applies the PURE plans from :mod:`lifecycle_scenarios` to the real canonical
repositories the API reads (tenant + user + ``tenant_implementation_plans`` +
``tenant_activations`` + the BYOD ``integration_connector_configs`` store), so
``E2E_TENANT_EMAIL_<SUITE>`` tenants exist and sign in with the supplied
password at the suite's C1 starting state.

Boundaries (enforced here, mirrors ``lifecycle_scenarios`` honesty law):

* NEVER writes a credential value, a secret reference, a ``sync_status``, a
  ``tenant_credentials`` revocation, a mapping-review evidence row, or any
  readiness/evidence token. Those are operator/env layer inputs the E2E run
  supplies with real credentials and real syncs.
* Only record-fact-false connector rows (all defaults: not enabled, no secret,
  never synced) are written, and only for connectors whose family is a valid
  BYOD ``ConnectorConfig`` type and whose manifest renders them where the suite
  expects them (suite C's comms cohort under Settings → Integrations).
* Never seeds ``tenant_activations.state='complete'`` (would need fabricated
  SDK/first-value evidence); returning tenants are seeded at the honest durable
  state the real activation API produces for an authenticated tenant.
* Idempotent: re-running converges the tenant/user/plan/activation/connector
  rows onto the declared plan. A user row whose ``tenant_id`` differs from the
  email-derived scenario tenant is refused (never hijacked). A connector row
  that has drifted off the all-false baseline (connected by a prior run) is
  left untouched and reported rather than clobbered.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import AdminRepository, UserRepository
from shared.auth.password import hash_password

from services.activation.models import ActivationRecord, ActivationState
from services.activation.repository import ActivationRepository
from services.integrations.connectors.base import ConnectorConfig
from services.integrations.connectors.service import ConnectorConfigRepository
from services.onboarding.models import TenantImplementationPlan
from services.onboarding.repositories import TenantImplementationPlanRepository

from .errors import SeedSafetyError
from .lifecycle_scenarios import (
    ACTIVATION_STATE_COMPLETE,
    LIFECYCLE_SUITES,
    LifecycleSuite,
    ScenarioPlan,
    scenario_state,
    tenant_email_env,
    tenant_password_env,
    validate_scenario_plan,
)
from .policy import assert_seed_allowed

logger = logging.getLogger("aether.demo_seed.lifecycle")

#: Provenance token distinguishing lifecycle-scenario tenants from the v1 demo
#: dataset (``synthetic_seed``). Demo ``reset``/``verify``/``status`` ignore
#: these rows (they own no ``demo_seed_record_ownership`` sidecars), so lifecycle
#: staging tenants that may later hold real operator credentials are never swept
#: up by demo dataset operations.
LIFECYCLE_SOURCE = "lifecycle_e2e_seed"

#: Deterministic-id namespace shared by every row of one scenario tenant so
#: re-seeding converges instead of duplicating.
_NS = uuid.UUID("71f0d5c1-9f70-4c1a-8b9a-8c2f35e1f0a1")

#: Durable principal shape verified against services/auth verify_email + login.
_ADMIN_PERMISSIONS: list[str] = ["read", "write", "ingest", "analytics", "billing", "admin"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def tenant_id_for_email(email: str) -> str:
    """Deterministic scenario-tenant id derived from the suite tenant email."""
    return str(uuid.uuid5(_NS, f"tenant:{email.strip().lower()}"))


def user_id_for_email(email: str) -> str:
    return str(uuid.uuid5(_NS, f"user:{email.strip().lower()}"))


def _plan_id(suite: LifecycleSuite, tenant_id: str) -> str:
    return f"lifecycle-impl-{suite.value.lower()}-{uuid.uuid5(_NS, f'plan:{tenant_id}').hex[:12]}"


def _activation_id(suite: LifecycleSuite, tenant_id: str) -> str:
    return f"lifecycle-act-{suite.value.lower()}-{uuid.uuid5(_NS, f'act:{tenant_id}').hex[:12]}"


def _connector_id(tenant_id: str, connector_type: str) -> str:
    return f"{tenant_id}:{connector_type}"


def _seed_markers(tenant_id: str, scenario: str) -> dict[str, str]:
    return {
        "data_origin": LIFECYCLE_SOURCE,
        "seed_source": LIFECYCLE_SOURCE,
        "seed_scenario": scenario,
        "tenant_id": tenant_id,
    }


def resolve_credentials(
    suite: LifecycleSuite,
    *,
    overrides_email: Optional[str] = None,
    overrides_password: Optional[str] = None,
    allow_shared: bool = True,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve (email, password) for one suite (harness-consistent).

    Explicit CLI overrides win, then the suite-scoped env vars
    (``E2E_TENANT_EMAIL_<SUITE>`` / ``E2E_TENANT_PASSWORD_<SUITE>``). When
    ``allow_shared`` (exactly one suite is being targeted — the ad-hoc harness
    posture) the shared ``E2E_TENANT_EMAIL`` / ``E2E_TENANT_PASSWORD`` pair is
    the fallback, mirroring ``lifecycleSuiteCredentials(suite)``.

    When seeding MULTIPLE suites (the normal ``seed-lifecycle`` run) the shared
    pair must NOT be used: each suite needs its OWN distinct tenant
    (``E2E_TENANT_EMAIL_A..F``), and a shared email would collapse every suite
    onto one tenant and overwrite its scenario state.
    """
    email = overrides_email or os.getenv(tenant_email_env(suite.value))
    password = overrides_password or os.getenv(tenant_password_env(suite.value))
    if (not email or not password) and allow_shared:
        email = email or os.getenv("E2E_TENANT_EMAIL")
        password = password or os.getenv("E2E_TENANT_PASSWORD")
    if not email or not password:
        return None, None
    return email, password


@dataclass
class LifecycleSeedResult:
    """Per-suite outcome of a ``seed-lifecycle`` run (JSON-serialisable)."""

    suite: str
    scenario: str
    email_provided: bool
    email: Optional[str] = None
    tenant_id: Optional[str] = None
    tenant_status: str = "skipped_no_email"
    plan_action: str = "none"
    activation_action: str = "none"
    connectors: list[dict[str, str]] = field(default_factory=list)
    operator_bound: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "scenario": self.scenario,
            "email_provided": self.email_provided,
            "email": self.email,
            "tenant_id": self.tenant_id,
            "tenant_status": self.tenant_status,
            "plan_action": self.plan_action,
            "activation_action": self.activation_action,
            "connectors": list(self.connectors),
            "operator_bound": list(self.operator_bound),
            "warnings": list(self.warnings),
        }


class LifecycleSeeder:
    """Applies one ``ScenarioPlan`` to the canonical repositories idempotently."""

    def __init__(self, *, environment: str, clock=_utc_now) -> None:
        self.environment = environment.strip().lower()
        self.clock = clock
        self.tenants = AdminRepository()
        self.users = UserRepository()
        self.plans = TenantImplementationPlanRepository()
        self.activations = ActivationRepository()
        self.connectors = ConnectorConfigRepository()

    # ── Tenant + user ─────────────────────────────────────────────────────────

    async def _ensure_tenant_user(
        self, plan: ScenarioPlan, *, email: str, password: str
    ) -> tuple[str, str]:
        """Create/repair the scenario tenant + sign-in-able admin user.

        Returns ``(tenant_id, tenant_status)`` where tenant_status is
        ``"created"`` or ``"already_existed"``. Refuses to hijack an email that
        already belongs to a different tenant.
        """
        tenant_id = tenant_id_for_email(email)
        existing_user = await self.users.find_by_email(email)
        if existing_user is not None and existing_user.get("tenant_id") != tenant_id:
            raise SeedSafetyError(
                f"email {email!r} already belongs to tenant "
                f"{existing_user.get('tenant_id')!r} (not the lifecycle-scenario "
                f"tenant {tenant_id!r}); pick an unused email or drop that tenant "
                "first — refusing to hijack an existing account"
            )
        tenant = await self.tenants.find_by_id(tenant_id)
        tenant_status = "already_existed" if tenant is not None else "created"

        name = f"Lifecycle {plan.suite.value} · {plan.name}"
        now = self.clock().isoformat()
        if tenant is None:
            await self.tenants.insert(tenant_id, {
                "tenant_id": tenant_id,
                "name": name,
                "contact_email": email,
                "plan": "alpha",
                "plan_tier": "alpha",
                "status": "active",
                "auth_method": "password",
                "settings": {},
                **_seed_markers(tenant_id, plan.suite.value),
                "seed_created_at": now,
            })
            tenant_status = "created"

        pw_hash = hash_password(password)
        now = self.clock().isoformat()
        user_payload = {
            "user_id": "",
            "tenant_id": tenant_id,
            "name": name,
            "password_hash": pw_hash,
            "status": "active",
            "email_verified": True,
            "auth_method": "password",
            "role": "admin",
            "permissions": list(_ADMIN_PERMISSIONS),
            "membership_status": "active",
            **_seed_markers(tenant_id, plan.suite.value),
        }
        if existing_user is not None:
            user_id = existing_user.get("user_id") or existing_user.get("id")
            await self.users.update(user_id, {**user_payload, "user_id": user_id})
        else:
            user_id = user_id_for_email(email)
            await self.users.insert(user_id, {
                **user_payload,
                "user_id": user_id,
                "email": email,
                "seed_created_at": now,
            })
        return tenant_id, tenant_status

    # ── Implementation plan (landing decision) ────────────────────────────────

    async def _ensure_plan(
        self, plan: ScenarioPlan, *, tenant_id: str
    ) -> str:
        """Upsert the tenant_implementation_plans row to ``landing_status``.

        An empty plan (no steps/blockers, ``success_criteria={}``) is the stable
        C1 carrier: ``/v1/onboarding/status`` recomputes low scores on read
        (go_live 13 / value 0 / expansion 14) and therefore never overrides a
        seeded ``live`` / ``not_started`` status.
        """
        existing = await self.plans.get_for_tenant(tenant_id)
        now = self.clock().isoformat()
        if existing is not None:
            plan_id = existing.get("implementation_plan_id") or existing.get("id")
            await self.plans.update(plan_id, {
                "implementation_plan_id": plan_id,
                "tenant_id": tenant_id,
                "status": plan.landing_status,
                "success_criteria": {},
                **_seed_markers(tenant_id, plan.suite.value),
                "updated_at": now,
            })
            return "updated"
        plan_id = _plan_id(plan.suite, tenant_id)
        payload = TenantImplementationPlan(
            implementation_plan_id=plan_id,
            tenant_id=tenant_id,
            status=plan.landing_status,
            created_at=now,
            updated_at=now,
        ).model_dump()
        payload["success_criteria"] = {}
        payload.update(_seed_markers(tenant_id, plan.suite.value))
        await self.plans.insert(plan_id, payload)
        return "created"

    # ── Activation record (durable WS-3 intents) ──────────────────────────────

    async def _ensure_activation(
        self, plan: ScenarioPlan, *, tenant_id: str
    ) -> str:
        """Seed/refresh the tenant's activation record with saved intents.

        Only suites with ``activation_record=True`` get a row. ``state`` is never
        ``complete``; returning tenants are set to ``account_verified`` + their
        saved intents (the honest durable record the real activation API writes
        for an authenticated tenant). A pre-existing genuinely-``complete``
        record (real evidence) is never regressed.
        """
        if not plan.activation_record:
            return "none"
        now = self.clock().isoformat()
        existing = await self.activations.get_for_tenant(tenant_id)
        intents = list(plan.intents)
        markers = _seed_markers(tenant_id, plan.suite.value)
        if existing is not None:
            act_id = existing.get("activation_id") or existing.get("id")
            if existing.get("state") == ACTIVATION_STATE_COMPLETE:
                await self.activations.update(act_id, {
                    "intents": intents,
                    "intents_updated_at": now,
                    "updated_at": now,
                    **markers,
                })
                return "updated_complete_preserved"
            await self.activations.update(act_id, {
                "state": plan.activation_state,
                "intents": intents,
                "intents_updated_at": now,
                "updated_at": now,
                **markers,
            })
            return "updated"
        act_id = _activation_id(plan.suite, tenant_id)
        record = ActivationRecord(
            activation_id=act_id,
            tenant_id=tenant_id,
            state=ActivationState(plan.activation_state),
            intents=intents,
            intents_updated_at=now,
            created_at=now,
            updated_at=now,
        ).model_dump()
        record.update(markers)
        await self.activations.insert(act_id, record)
        return "created"

    # ── Connector rows (record-fact-false only) ───────────────────────────────

    async def _ensure_connectors(
        self, plan: ScenarioPlan, *, tenant_id: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Upsert only the plan's genuinely record-fact-false connector rows.

        A baseline row already exists if untouched (never rewritten). A row that
        drifted off baseline (a prior run connected it) is left untouched and
        reported ``exists-connected`` — the runbook's full reset restores it.
        """
        connector_rows: list[dict[str, str]] = []
        for presence in plan.seedable_connectors:
            key = _connector_id(tenant_id, presence.family)
            existing = await self.connectors.find_by_id(key)
            if existing is None:
                cfg = ConnectorConfig(
                    tenant_id=tenant_id,
                    connector_type=presence.family,  # type: ignore[arg-type]
                )
                payload = cfg.model_dump()
                payload["config_id"] = (
                    f"conn_{uuid.uuid5(_NS, f'cfg:{key}').hex[:12]}"
                )
                payload.update(_seed_markers(tenant_id, plan.suite.value))
                await self.connectors.insert(key, payload)
                connector_rows.append({"family": presence.family, "action": "created"})
                continue
            drifted = bool(
                existing.get("enabled")
                or existing.get("secret_configured")
                or (existing.get("sync_status") not in (None, "never_synced"))
            )
            if drifted:
                connector_rows.append(
                    {"family": presence.family, "action": "exists-connected"}
                )
            else:
                connector_rows.append(
                    {"family": presence.family, "action": "exists-baseline"}
                )
        operator_bound = [
            f"{p.family}: {p.marker or 'operator/evidence-bound'}"
            for p in plan.operator_bound_connectors
        ]
        return connector_rows, operator_bound

    # ── One suite ─────────────────────────────────────────────────────────────

    async def seed_suite(
        self,
        suite: LifecycleSuite,
        *,
        email: str,
        password: str,
    ) -> LifecycleSeedResult:
        """Apply the suite's scenario plan (raises SeedSafetyError on refusal)."""
        plan = scenario_state(suite)
        validate_scenario_plan(plan)
        # Policy gate first, BEFORE any write: refusing production / non-loopback
        # DB / non-allowlisted staging must leave the store untouched.
        tenant_id = tenant_id_for_email(email)
        assert_seed_allowed(environment=self.environment, tenant_id=tenant_id)

        result = LifecycleSeedResult(
            suite=suite.value,
            scenario=plan.name,
            email_provided=True,
            email=email,
        )
        tenant_id, tenant_status = await self._ensure_tenant_user(
            plan, email=email, password=password
        )
        result.tenant_id = tenant_id
        result.tenant_status = tenant_status

        result.plan_action = await self._ensure_plan(plan, tenant_id=tenant_id)
        result.activation_action = await self._ensure_activation(
            plan, tenant_id=tenant_id
        )
        result.connectors, result.operator_bound = await self._ensure_connectors(
            plan, tenant_id=tenant_id
        )
        result.warnings.extend(plan.operator_steps)
        return result

    async def seed_many(
        self,
        suites: list[LifecycleSuite],
        *,
        credentials: dict[LifecycleSuite, tuple[str, str]],
    ) -> dict[str, Any]:
        """Seed every suite in ``suites`` that has credentials; skip the rest."""
        rows: list[dict[str, Any]] = []
        for suite in LIFECYCLE_SUITES:
            if suite not in suites:
                continue
            creds = credentials.get(suite)
            if creds is None:
                rows.append(
                    LifecycleSeedResult(
                        suite=suite.value,
                        scenario=scenario_state(suite).name,
                        email_provided=False,
                        tenant_status="skipped_no_email",
                    ).to_dict()
                )
                continue
            email, password = creds
            rows.append(
                (await self.seed_suite(suite, email=email, password=password)).to_dict()
            )
        return {
            "environment": self.environment,
            "seed_source": LIFECYCLE_SOURCE,
            "suites": rows,
        }


__all__ = [
    "LIFECYCLE_SOURCE",
    "LifecycleSeedResult",
    "LifecycleSeeder",
    "resolve_credentials",
    "tenant_id_for_email",
    "user_id_for_email",
]
