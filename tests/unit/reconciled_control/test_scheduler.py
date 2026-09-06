"""Phase-3 continuous reconcile scheduler tests (blueprint §32/§35/§39).

Covers one ``run_scheduler_pass`` sweep (freshness skip, tenant scoping,
reconcile-run persistence + ``last_reconcile_*`` stamps, plan persistence,
governed execution with and without admitted §36 authorities, honest
missing-evidence ``unknown``) and the flag-gated supervised loop
(``build_reconcile_scheduler_coro`` self-stops when flags flip off, never runs
two passes concurrently, re-reads interval per pass).

Boundaries asserted here:

* with the default actuator registry (no admitted authority) execution fails
  closed into ``blocked`` + ActionRequired — nothing fabricates success;
* an R1 (behavioral) plan defers to ``waiting_approval`` on the missing
  ``gate:simulation`` §21 token even when its actuator authority is admitted;
* no evidence loader → availability ``missing`` → reconcile ``unknown`` —
  absence of evidence is never turned into drift or a plan.

Every store get_pool is pinned to None (in-memory) and the stores are reset
by the reconciled_control conftest before and after each test.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from services.managed_integrations import scheduler as scheduler_module
from services.managed_integrations.actuators import (
    ActuatorApplyResult,
    ActuatorVerifyResult,
    registry_with_authorities,
)
from services.managed_integrations.change_sets_repository import (
    get_change_set_repository,
)
from services.managed_integrations.contracts import ChangeSpec, ObservedStateSnapshot
from services.managed_integrations.desired_policy import build_desired_state
from services.managed_integrations.execution_records_repository import (
    get_action_required_repository,
    get_change_set_event_repository,
    get_last_known_good_repository,
)
from services.managed_integrations.repository import (
    get_managed_integration_repository,
    get_reconcile_run_repository,
)

NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
TENANT = "tenant-rcp-sched"
OTHER_TENANT = "tenant-rcp-sched-other"
ENV = "env-prod-1"
ACTOR = "reconcile-scheduler"


@pytest.fixture(autouse=True)
def _scheduler_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every store get_pool the scheduler sweep touches to None.

    Four targets: the registration/reconcile-run store
    (``managed_integrations.repository``), the ChangeSet store
    (``change_sets_repository``), the Phase-2 execution-records stores
    (``execution_records_repository``) and the shared ``repositories.repos``
    source every module imports its ``get_pool`` from.
    """
    import repositories.repos as repos_module
    import services.managed_integrations.change_sets_repository as cs_module
    import services.managed_integrations.execution_records_repository as er_module
    import services.managed_integrations.repository as mi_module

    async def _no_pool() -> None:
        return None

    monkeypatch.setattr(mi_module, "get_pool", _no_pool)
    monkeypatch.setattr(cs_module, "get_pool", _no_pool)
    monkeypatch.setattr(er_module, "get_pool", _no_pool)
    monkeypatch.setattr(repos_module, "get_pool", _no_pool)


# ── evidence + registration helpers ─────────────────────────────────────────


def _desired(
    mi: str, *, tenant_id: str = TENANT, environment_id: str = ENV
) -> object:
    """Managed-stable desired spec whose durable id matches the row ref."""
    return build_desired_state(
        managed_integration_id=mi,
        tenant_id=tenant_id,
        environment_id=environment_id,
        desired_state_id=f"rcds_{mi}",
        revision="1",
    )


def _observed(
    mi: str,
    *,
    tenant_id: str = TENANT,
    environment_id: str = ENV,
    runtime_version: str = "8.1.3",
    health_status: Optional[str] = None,
    observed_at: datetime = NOW,
    reported_source_identity: Optional[str] = None,
) -> ObservedStateSnapshot:
    """Live-observation snapshot whose durable id matches the row ref."""
    return ObservedStateSnapshot(
        observed_state_id=f"rcobs_{mi}",
        managed_integration_ref=mi,
        tenant_id=tenant_id,
        environment_id=environment_id,
        observed_at=observed_at,
        received_at=observed_at,
        provenance="unknown",
        availability="available",
        runtime_version=runtime_version,
        health_status=health_status,
        reported_source_identity=reported_source_identity or mi,
    )


async def _register_row(
    mi: str,
    *,
    tenant_id: str = TENANT,
    environment_id: str = ENV,
    last_reconcile_at: Optional[datetime] = None,
    last_reconcile_result: Optional[str] = None,
    desired_state_ref: Optional[str] = None,
    observed_state_ref: Optional[str] = None,
) -> dict:
    return await get_managed_integration_repository().register(
        managed_integration_id=mi,
        tenant_id=tenant_id,
        environment_id=environment_id,
        integration_kind="sdk_web",
        source_ref=f"inst-{mi}",
        source_origin="tenant",
        source_owner="tenant",
        release_channel="managed_stable",
        desired_state_ref=desired_state_ref,
        observed_state_ref=observed_state_ref,
        last_reconcile_at=last_reconcile_at,
        last_reconcile_result=last_reconcile_result,
    )


def _evidence_loader(
    evidence: dict,
) -> object:
    """Build an async loader serving per-integration (desired, observed)."""

    async def _load(row: dict, now: datetime) -> Optional[tuple]:
        entry = evidence.get(str(row.get("managed_integration_id")))
        if entry is None:
            return None
        desired, observed = entry
        return desired, observed, None

    return _load


async def _row(
    mi: str, *, tenant_id: str = TENANT, environment_id: str = ENV
) -> Optional[dict]:
    """Fetch one registration row by id (list newest-first, filter in memory)."""
    rows = [
        r
        for r in await get_managed_integration_repository().list(
            tenant_id=tenant_id, environment_id=environment_id
        )
        if r.get("managed_integration_id") == mi
    ]
    return rows[0] if rows else None


# ── §36 recording authority (mirrors test_executor) ─────────────────────────


class RecordingAuthority:
    """Records every §36 lifecycle call; applies and verifies successfully."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.applied: list[ChangeSpec] = []
        self.verified: list[ChangeSpec] = []

    async def apply(self, change: ChangeSpec, actuator: object) -> ActuatorApplyResult:
        self.calls.append("apply")
        self.applied.append(change)
        return ActuatorApplyResult(
            outcome="applied",
            before_state_ref="ds:before",
            after_state_ref="ds:after",
        )

    async def verify(self, change: ChangeSpec, actuator: object) -> ActuatorVerifyResult:
        self.calls.append("verify")
        self.verified.append(change)
        return ActuatorVerifyResult()

    async def rollback(self, change: ChangeSpec, actuator: object) -> ActuatorApplyResult:
        self.calls.append("rollback")
        return ActuatorApplyResult(outcome="applied")


# ── mandated scenarios ──────────────────────────────────────────────────────


async def test_fresh_integrations_are_skipped_and_tenant_filter_scopes_sweep() -> None:
    """Scenario 1: last_reconcile_at inside the 300 s §32 window → skipped.

    The sweep is also scoped by ``tenant_filter``: registrations in another
    tenant are neither scanned nor stamped.
    """
    await _register_row(
        "mi-sdk-fresh",
        last_reconcile_at=NOW - timedelta(seconds=120),
        last_reconcile_result="match",
    )
    await _register_row(
        "mi-sdk-other-tenant",
        tenant_id=OTHER_TENANT,
        last_reconcile_at=None,
    )

    summary = await scheduler_module.run_scheduler_pass(now=NOW, tenant_filter=TENANT)

    assert summary == {
        "integrations_scanned": 1,
        "skipped_fresh": 1,
        "reconcile_results": {},
        "plans_created": [],
        "execution_outcomes": [],
        "errors": [],
    }
    # No reconcile runs, no plans, no stamps on either row.
    assert (
        await get_reconcile_run_repository().latest_for_integration(
            tenant_id=TENANT, environment_id=ENV, managed_integration_id="mi-sdk-fresh"
        )
    ) is None
    assert (
        await get_change_set_repository().list(tenant_id=TENANT, environment_id=ENV)
        == []
    )
    other = await _row("mi-sdk-other-tenant", tenant_id=OTHER_TENANT)
    assert other is not None and other.get("last_reconcile_at") is None


async def test_match_and_acceptable_drift_reconcile_without_plans() -> None:
    """Scenario 2: match / acceptable_drift → runs persisted, no plan, no exec."""
    await _register_row(
        "mi-sdk-1",
        desired_state_ref="rcds_mi-sdk-1",
        observed_state_ref="rcobs_mi-sdk-1",
    )
    await _register_row(
        "mi-sdk-2",
        desired_state_ref="rcds_mi-sdk-2",
        observed_state_ref="rcobs_mi-sdk-2",
    )
    loader = _evidence_loader(
        {
            "mi-sdk-1": (
                _desired("mi-sdk-1"),
                _observed("mi-sdk-1", runtime_version="8.1.3"),
            ),
            # 7.9.0 is deprecated-but-served at the managed_stable floor.
            "mi-sdk-2": (
                _desired("mi-sdk-2"),
                _observed("mi-sdk-2", runtime_version="7.9.0"),
            ),
        }
    )

    summary = await scheduler_module.run_scheduler_pass(
        now=NOW, evidence_loader=loader
    )

    assert summary["integrations_scanned"] == 2
    assert summary["skipped_fresh"] == 0
    assert summary["errors"] == []
    assert summary["plans_created"] == []
    assert summary["execution_outcomes"] == []
    assert summary["reconcile_results"]["mi-sdk-1"]["result"] == "match"
    assert summary["reconcile_results"]["mi-sdk-2"]["result"] == "acceptable_drift"
    assert summary["reconcile_results"]["mi-sdk-1"]["drift_count"] == 0
    assert summary["reconcile_results"]["mi-sdk-2"]["drift_count"] == 1
    # Runs persisted; registration rows stamped with the reconcile result.
    run_1 = await get_reconcile_run_repository().latest_for_integration(
        tenant_id=TENANT, environment_id=ENV, managed_integration_id="mi-sdk-1"
    )
    run_2 = await get_reconcile_run_repository().latest_for_integration(
        tenant_id=TENANT, environment_id=ENV, managed_integration_id="mi-sdk-2"
    )
    assert run_1 is not None and run_1.get("result") == "match"
    assert run_2 is not None and run_2.get("result") == "acceptable_drift"
    assert (await _row("mi-sdk-1")).get("last_reconcile_result") == "match"
    assert (await _row("mi-sdk-2")).get("last_reconcile_result") == "acceptable_drift"
    # No ChangeSet exists for either integration.
    assert (
        await get_change_set_repository().list(tenant_id=TENANT, environment_id=ENV)
        == []
    )


async def test_actionable_drift_plan_persisted_but_default_registry_fails_closed() -> None:
    """Scenario 3: actionable → planned; default §36 registry → blocked + §12.14.

    The health drift produces a trivial R0 notification plan whose automation
    authority allows execution, but with no admitted actuator authority the
    executor fails closed: plan row ``blocked``, one ActionRequired row, and
    the registration row untouched apart from its ``last_reconcile_*`` stamps.
    """
    mi = "mi-sdk-1"
    before = await _register_row(
        mi,
        desired_state_ref="rcds_mi-sdk-1",
        observed_state_ref="rcobs_mi-sdk-1",
    )
    loader = _evidence_loader(
        {
            mi: (
                _desired(mi),
                _observed(mi, health_status="degraded"),
            )
        }
    )

    summary = await scheduler_module.run_scheduler_pass(now=NOW, evidence_loader=loader)

    # ── summary ───────────────────────────────────────────────────────────
    assert summary["integrations_scanned"] == 1
    assert summary["skipped_fresh"] == 0
    assert summary["errors"] == []
    assert summary["reconcile_results"][mi]["result"] == "actionable_drift"
    assert summary["reconcile_results"][mi]["drift_count"] == 1
    assert len(summary["plans_created"]) == 1
    changeset_id = summary["plans_created"][0]
    assert len(summary["execution_outcomes"]) == 1
    outcome = summary["execution_outcomes"][0]
    assert outcome["changeset_id"] == changeset_id
    assert outcome["managed_integration_ref"] == mi
    assert outcome["reached_status"] == "blocked"
    assert outcome["ok"] is False
    assert outcome["missing_tokens"] == []
    assert len(outcome["action_required_ids"]) == 1

    # ── plan row ended blocked with the preflight failure ──────────────────
    plan_row = await get_change_set_repository().get(TENANT, ENV, changeset_id)
    assert plan_row is not None
    assert plan_row.get("status") == "blocked"
    assert plan_row.get("initiator") == ACTOR
    events = await get_change_set_event_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_id=changeset_id
    )
    assert any(e.get("to_status") == "blocked" for e in events)
    assert all(e.get("actor") == ACTOR for e in events)

    # ── one open §12.14 ActionRequired row, fail-closed reason ─────────────
    action_rows = await get_action_required_repository().list(
        tenant_ref=TENANT, status="open"
    )
    assert len(action_rows) == 1
    ar = action_rows[0]
    assert ar.get("managed_integration_ref") == mi
    assert ar.get("action_type") == "preflight_failed"
    assert "no admitted authority" in (ar.get("reason") or "")
    assert ar.get("action_id") in outcome["action_required_ids"]
    # No LKG was established by a blocked run.
    assert (
        await get_last_known_good_repository().get_for_integration(TENANT, ENV, mi)
        is None
    )

    # ── registration row: only the reconcile stamps changed ────────────────
    after = await _row(mi)
    stamped = {"last_reconcile_at", "last_reconcile_result", "updated_at"}
    assert {
        k: v for k, v in after.items() if k not in stamped
    } == {k: v for k, v in before.items() if k not in stamped}
    assert after.get("last_reconcile_result") == "actionable_drift"
    assert after.get("observed_state_ref") == "rcobs_mi-sdk-1"


async def test_loop_self_stops_when_flags_off_and_leaves_stores_untouched(
    rcp_flags,
) -> None:
    """Scenario 4: flags-off parity — the loop returns without any side effect.

    Even with the master ``enabled`` flag on, ``scheduler_enabled`` False
    stops the loop on its first gate check: no sweep runs, no store is
    touched, and the registration row stays byte-identical.
    """
    rcp_flags(enabled=True)  # master on, scheduler flag off → AND gate stops
    mi = "mi-sdk-flags-off"
    before = await _register_row(mi)

    factory = scheduler_module.build_reconcile_scheduler_coro()
    coro = factory()
    assert asyncio.iscoroutine(coro)
    # A fresh factory call yields a distinct coroutine object.
    second = factory()
    assert coro is not second
    second.close()
    await asyncio.wait_for(coro, timeout=2)

    assert await _row(mi) == before
    assert (
        await get_reconcile_run_repository().list_for_integration(
            tenant_id=TENANT, environment_id=ENV, managed_integration_id=mi
        )
        == []
    )
    assert (
        await get_change_set_repository().list(tenant_id=TENANT, environment_id=ENV)
        == []
    )
    assert (
        await get_action_required_repository().list(tenant_ref=TENANT, status="open")
        == []
    )


async def test_admitted_authority_auto_commits_and_establishes_lkg() -> None:
    """Scenario 5: automation-allowed R0 plan with admitted §36 authority.

    With a ``notification_action`` authority admitted through
    ``registry_with_authorities`` the R0 health-notification plan executes end
    to end: ``committed``, evidence recorded, and the §32 step-21 LKG is
    established on the row's durable desired-state ref. (Version/capability
    upgrades are R1 and cannot commit through this Phase-2 executor without an
    operator-recorded ``gate:simulation`` approval — covered separately.)
    """
    mi = "mi-sdk-5"
    await _register_row(
        mi,
        desired_state_ref="rcds_mi-sdk-5",
        observed_state_ref="rcobs_mi-sdk-5",
    )
    loader = _evidence_loader(
        {mi: (_desired(mi), _observed(mi, health_status="degraded"))}
    )
    authority = RecordingAuthority()
    registry = registry_with_authorities({"notification_action": authority})

    summary = await scheduler_module.run_scheduler_pass(
        now=NOW, evidence_loader=loader, registry=registry
    )

    assert summary["errors"] == []
    assert summary["reconcile_results"][mi]["result"] == "actionable_drift"
    assert len(summary["plans_created"]) == 1
    changeset_id = summary["plans_created"][0]
    assert len(summary["execution_outcomes"]) == 1
    outcome = summary["execution_outcomes"][0]
    assert outcome["changeset_id"] == changeset_id
    assert outcome["reached_status"] == "committed"
    assert outcome["ok"] is True
    assert outcome["lkg_id"] is not None
    assert outcome["missing_tokens"] == []
    assert outcome["action_required_ids"] == []

    # The §36 authority really ran: applied, then verified.
    assert authority.calls == ["apply", "verify"]
    assert [c.action for c in authority.applied] == ["notification_action"]

    # Plan row committed with the executor events attributed to the scheduler.
    plan_row = await get_change_set_repository().get(TENANT, ENV, changeset_id)
    assert plan_row is not None and plan_row.get("status") == "committed"
    events = await get_change_set_event_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_id=changeset_id
    )
    assert any(e.get("to_status") == "committed" for e in events)
    assert all(e.get("actor") == ACTOR for e in events)

    # LKG established only now, keyed on the row's durable desired-state ref.
    lkg = await get_last_known_good_repository().get_for_integration(TENANT, ENV, mi)
    assert lkg is not None
    assert lkg.get("lkg_id") == outcome["lkg_id"]
    assert lkg.get("desired_state_ref") == "rcds_mi-sdk-5"
    assert lkg.get("managed_integration_ref") == mi

    # No ActionRequired was fabricated on the success path.
    assert (
        await get_action_required_repository().list(tenant_ref=TENANT, status="open")
        == []
    )


async def test_loop_interval_wiring_stops_after_flag_flip(monkeypatch, rcp_flags) -> None:
    """Scenario 6: deterministic loop wiring with a pinned 1 s interval.

    ``asyncio.sleep`` is replaced with a recorder that flips the scheduler
    flag off inside the first sleep; the loop re-checks flags at the top of
    the next pass and returns — proving interval re-read per pass, the
    self-stop gate, and that only one sleep ever happens.
    """
    rcp_flags(enabled=True, scheduler_enabled=True)  # gate ON before the loop
    sleeps: list = []
    state_after_flip: list = []

    async def _flip_then_sleep(delay: float) -> None:
        sleeps.append(delay)
        state_after_flip.append(rcp_flags(enabled=True, scheduler_enabled=False))

    monkeypatch.setattr(asyncio, "sleep", _flip_then_sleep)
    coro = scheduler_module.build_reconcile_scheduler_coro(interval_seconds=1)()
    await asyncio.wait_for(coro, timeout=2)

    # The pinned interval was applied, the loop slept exactly once, and the
    # flag flip inside that sleep self-stopped the loop on the next gate check.
    assert sleeps == [1]
    assert len(state_after_flip) == 1
    assert state_after_flip[0].scheduler_enabled is False


async def test_r1_plan_defers_to_waiting_approval_even_with_admitted_authority() -> None:
    """Extra: an admitted repository_upgrade authority cannot commit an R1 plan.

    Version drift below the managed_stable floor plans a behavioral
    repository_upgrade (R1, token ``gate:simulation``). The executor defers it
    to ``waiting_approval`` with the missing §21 token — the authority is
    never invoked — because the scheduler itself never grants approvals. This
    is the honest Phase-2 boundary the auto-commit scenario must not paper
    over.
    """
    mi = "mi-sdk-r1"
    await _register_row(
        mi,
        desired_state_ref="rcds_mi-sdk-r1",
        observed_state_ref="rcobs_mi-sdk-r1",
    )
    loader = _evidence_loader(
        {mi: (_desired(mi), _observed(mi, runtime_version="6.4.2"))}
    )
    authority = RecordingAuthority()
    registry = registry_with_authorities({"repository_upgrade": authority})

    summary = await scheduler_module.run_scheduler_pass(
        now=NOW, evidence_loader=loader, registry=registry
    )

    assert summary["errors"] == []
    assert summary["reconcile_results"][mi]["result"] == "actionable_drift"
    assert len(summary["plans_created"]) == 1
    changeset_id = summary["plans_created"][0]
    assert len(summary["execution_outcomes"]) == 1
    outcome = summary["execution_outcomes"][0]
    assert outcome["reached_status"] == "waiting_approval"
    assert outcome["ok"] is False
    assert outcome["missing_tokens"] == ["gate:simulation"]
    assert authority.calls == []  # nothing applied without the §21 token

    plan_row = await get_change_set_repository().get(TENANT, ENV, changeset_id)
    assert plan_row is not None
    assert plan_row.get("status") == "waiting_approval"
    assert (plan_row.get("risk") or {}).get("risk_class") == "R1"
    events = await get_change_set_event_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_id=changeset_id
    )
    assert any(
        e.get("to_status") == "waiting_approval"
        and "approval tokens" in (e.get("reason") or "")
        for e in events
    )
    # Deferral surfaces no ActionRequired and no fabricated LKG.
    assert (
        await get_action_required_repository().list(tenant_ref=TENANT, status="open")
        == []
    )
    assert (
        await get_last_known_good_repository().get_for_integration(TENANT, ENV, mi)
        is None
    )


async def test_no_evidence_loader_reconciles_unknown_and_never_plans() -> None:
    """Extra: absent evidence → honest ``unknown``, never actionable.

    With no ``evidence_loader`` wired, a stale registration reconciles against
    a missing-observation snapshot (availability ``missing``): the run is
    persisted as ``unknown``, the row is stamped, and no plan is fabricated
    from the absence of evidence.
    """
    mi = "mi-sdk-no-evidence"
    before = await _register_row(mi)

    summary = await scheduler_module.run_scheduler_pass(now=NOW)

    assert summary["errors"] == []
    assert summary["integrations_scanned"] == 1
    assert summary["skipped_fresh"] == 0
    assert summary["plans_created"] == []
    assert summary["execution_outcomes"] == []
    assert summary["reconcile_results"][mi]["result"] == "unknown"
    assert summary["reconcile_results"][mi]["drift_count"] == 0

    run_row = await get_reconcile_run_repository().latest_for_integration(
        tenant_id=TENANT, environment_id=ENV, managed_integration_id=mi
    )
    assert run_row is not None and run_row.get("result") == "unknown"
    assert "missing" in (run_row.get("note") or "")

    after = await _row(mi)
    assert after.get("last_reconcile_result") == "unknown"
    assert after.get("observed_state_ref") is None
    # Registration columns untouched apart from the reconcile stamps.
    stamped = {"last_reconcile_at", "last_reconcile_result", "updated_at"}
    assert {
        k: v for k, v in after.items() if k not in stamped
    } == {k: v for k, v in before.items() if k not in stamped}
