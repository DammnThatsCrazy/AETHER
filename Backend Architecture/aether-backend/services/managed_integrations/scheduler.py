"""Phase-3 continuous reconcile scheduler (blueprint §32/§35/§39).

Turns the Phase-0 reconcile engine (``reconciler.reconcile``), the Phase-1
planner (``change_planning.build_plan``) and the Phase-2 governed executor
(``executor.run_changeset``) into one continuous, flag-gated loop:

* one pass sweeps the registered managed integrations, skipping any whose
  ``last_reconcile_at`` sits inside the §32 freshness window (300 s);
* a stale integration is reconciled against evidence supplied through the
  ``evidence_loader`` seam (the caller owns observation plumbing); when no
  loader is wired the engine reconciles against an honest missing-observation
  snapshot and classifies ``unknown`` — never actionable from missing
  evidence;
* actionable drift is planned (§32 step 12) and persisted only when the
  planner returns a deterministic candidate (drift with no remediation stays
  surfaced by the reconcile run); the plan carries the §35 guard revisions it
  was planned against and is promoted ``draft -> planned`` before creation;
* a persisted plan runs through the §34 executor only when the §39 risk
  engine's automation authority allows it (``risk.automation_allowed``).

Boundaries (Phase 3):

* nothing auto-executes unless ``flags.enabled()`` AND
  ``flags.scheduler_enabled()`` are both true; the module is importable with
  all flags OFF, does nothing at import time, and never enables itself;
* execution additionally requires the §39 risk decision and the §34
  executor's §21 token gates; the scheduler itself never grants approvals and
  never admits actuator authorities;
* with the default §36 actuator registry (no admitted authority) execution
  fails closed into ``blocked`` plus a §12.14 ActionRequired row — the
  scheduler never fabricates success;
* every mutation rides ``run_changeset``; the scheduler never mutates an
  integration row directly (it only stamps ``last_reconcile_*`` through
  ``mark_reconciled`` after each reconcile run).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from shared.temporal.instant import coerce_utc_lenient

if TYPE_CHECKING:
    from services.managed_integrations.contracts import (
        DesiredStateSpec,
        ObservedStateSnapshot,
    )

__all__ = ["run_scheduler_pass", "build_reconcile_scheduler_coro"]

# Actor recorded on every executor transition the scheduler drives.
_SCHEDULER_ACTOR = "reconcile-scheduler"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(instant: datetime) -> datetime:
    """Normalize an instant for comparisons (naive instants assume UTC).

    Delegates to the temporal kernel: ``coerce_utc_lenient`` is the sanctioned
    home of the assume-UTC-on-naive policy (temporal-integrity gate), so the
    replace-with-tz logic lives there, not here.
    """
    coerced = coerce_utc_lenient(instant)
    assert coerced is not None  # a datetime input always coerces
    return coerced


def _parse_last_reconcile_at(raw: Any) -> Optional[datetime]:
    """Parse a stored ``last_reconcile_at`` instant; None when absent/unparseable.

    Mirrors the registration store's ``_parse_ts`` handling of TIMESTAMPTZ:
    in-memory rows store ``isoformat()`` strings; an unparseable value is
    treated as never-reconciled (stale), never as fresh. Parsing + naive-input
    policy come from the temporal kernel (``coerce_utc_lenient``).
    """
    if raw is None or isinstance(raw, bool):
        return None
    return coerce_utc_lenient(raw)


def _is_fresh(now: datetime, raw_last_reconcile_at: Any, window_seconds: int) -> bool:
    """§32 freshness: reconciled within ``window_seconds`` → skip this pass."""
    last = _parse_last_reconcile_at(raw_last_reconcile_at)
    if last is None:
        return False
    return (now - last).total_seconds() <= window_seconds


def _missing_observation(
    row: dict, now: datetime
) -> tuple[DesiredStateSpec, ObservedStateSnapshot, Optional[dict[str, str]]]:
    """Honest no-evidence snapshot: availability ``missing`` (never actionable).

    Built only from durable registration facts (desired pointer + release
    channel + schema fingerprint) plus a synthetic observation marker, the same
    ``rcobs_`` convention ``sensors`` uses when nothing was observed. Reconcile
    classifies availability ``missing`` as ``unknown`` — the scheduler never
    turns absence of evidence into drift.
    """
    from services.managed_integrations.contracts import (
        DesiredStateSpec,
        ObservedStateSnapshot,
    )

    ref = str(row["managed_integration_id"])
    desired_state_id = row.get("desired_state_ref") or f"rcds_{ref[:12]}"
    desired = DesiredStateSpec(
        desired_state_id=str(desired_state_id),
        managed_integration_ref=ref,
        tenant_id=str(row["tenant_id"]),
        environment_id=str(row["environment_id"]),
        revision="1",
        release_channel=str(row.get("release_channel") or "managed_stable"),
        schema_fingerprint=row.get("schema_fingerprint"),
        created_at=now,
    )
    observed = ObservedStateSnapshot(
        observed_state_id=f"rcobs_{ref[:12]}",
        managed_integration_ref=ref,
        tenant_id=str(row["tenant_id"]),
        environment_id=str(row["environment_id"]),
        observed_at=now,
        received_at=now,
        provenance="unknown",
        availability="missing",
    )
    return desired, observed, None


def _summary_entry(view: Any) -> dict[str, Any]:
    """One reconcile result record for the pass summary."""
    return {
        "result": view.result,
        "reconcile_id": view.reconcile_id,
        "desired_revision": view.desired_revision,
        "observed_revision": view.observed_revision,
        "drift_count": len(view.drift),
    }


def _outcome_entry(mi: str, outcome: Any) -> dict[str, Any]:
    """One execution outcome record for the pass summary (all §34 run facts)."""
    return {
        "changeset_id": outcome.changeset_id,
        "managed_integration_ref": mi,
        "reached_status": outcome.reached_status,
        "ok": outcome.ok,
        "superseded": outcome.superseded,
        "lkg_id": outcome.lkg_id,
        "missing_tokens": list(outcome.missing_tokens),
        "action_required_ids": list(outcome.action_required_ids),
        "reason": outcome.reason,
    }


async def run_scheduler_pass(
    *,
    registry: Optional[Any] = None,
    now: Optional[datetime] = None,
    tenant_filter: Optional[str] = None,
    evidence_loader: Optional[
        Callable[
            [dict, datetime],
            Awaitable[
                Optional[tuple[DesiredStateSpec, ObservedStateSnapshot, Optional[dict[str, str]]]]
            ],
        ]
    ] = None,
) -> dict[str, Any]:
    """Run one continuous-reconcile sweep over registered integrations (§32/§39).

    Each registration row is either skipped (last reconcile inside the
    freshness window) or reconciled, its run persisted to ``reconcile_runs``
    and its row stamped via ``mark_reconciled`` so the window advances.
    Actionable drift is planned and persisted as a ``planned`` ChangeSet when
    the planner returns a candidate; the plan executes only when
    ``risk.automation_allowed`` and the executor's §21 token gates pass.

    ``evidence_loader`` (optional) is awaited per stale integration as
    ``loader(row, now)`` and returns ``(DesiredStateSpec,
    ObservedStateSnapshot, observed_capabilities)`` or ``None`` — None (or an
    absent loader) falls back to the missing-observation path above. The
    loader's snapshot must reference the row's integration, or the sweep
    records an error for that row.

    ``registry`` is the §36 actuator registry handed to the executor (the
    executor's default — no admitted authority — fails closed into
    ``blocked`` + ActionRequired). ``tenant_filter`` scopes the sweep to one
    tenant. The sweep covers one page of the registration list (limit 200);
    pagination is left to the caller's cadence.

    Returns the pass summary with keys ``integrations_scanned``,
    ``skipped_fresh``, ``reconcile_results`` (by managed integration),
    ``plans_created``, ``execution_outcomes`` and ``errors`` — always an
    honest report, never fabricated success.
    """
    from services.managed_integrations.change_planning import build_plan, with_status
    from services.managed_integrations.change_sets_repository import (
        get_change_set_repository,
    )
    from services.managed_integrations.execution_records_repository import (
        get_last_known_good_repository,
    )
    from services.managed_integrations.executor import TargetSnapshot, run_changeset
    from services.managed_integrations.reconciler import (
        DEFAULT_FRESHNESS_WINDOW_SECONDS,
        reconcile,
    )
    from services.managed_integrations.repository import (
        get_managed_integration_repository,
        get_reconcile_run_repository,
    )
    from shared.logger.logger import get_logger

    logger = get_logger("aether.managed_integrations.scheduler")
    instant = _as_utc(now or _utc_now())
    summary: dict[str, Any] = {
        "integrations_scanned": 0,
        "skipped_fresh": 0,
        "reconcile_results": {},
        "plans_created": [],
        "execution_outcomes": [],
        "errors": [],
    }

    mi_repo = get_managed_integration_repository()
    run_repo = get_reconcile_run_repository()
    rows = await mi_repo.list(tenant_id=tenant_filter)
    summary["integrations_scanned"] = len(rows)

    for row in rows:
        mi = str(row["managed_integration_id"])
        tenant_id = str(row["tenant_id"])
        environment_id = str(row["environment_id"])
        if _is_fresh(
            instant, row.get("last_reconcile_at"), DEFAULT_FRESHNESS_WINDOW_SECONDS
        ):
            summary["skipped_fresh"] += 1
            continue
        try:
            # ── evidence ───────────────────────────────────────────────────
            loaded: Optional[Any] = None
            if evidence_loader is not None:
                loaded = await evidence_loader(row, instant)
            had_evidence = loaded is not None
            if loaded is None:
                desired, observed, capabilities = _missing_observation(row, instant)
            else:
                desired, observed, capabilities = loaded
                if observed.managed_integration_ref != mi:
                    raise ValueError(
                        "evidence loader returned a snapshot for "
                        f"{observed.managed_integration_ref!r}, expected {mi!r}"
                    )

            # ── reconcile + persist the run (§32) ─────────────────────────
            view = reconcile(
                managed_integration_id=mi,
                tenant_id=tenant_id,
                environment_id=environment_id,
                integration_kind=str(row["integration_kind"]),
                expected_identity=mi,
                desired=desired,
                observed=observed,
                observed_capabilities=capabilities,
                freshness_window_seconds=DEFAULT_FRESHNESS_WINDOW_SECONDS,
                now=instant,
            )
            await run_repo.create(view)
            await mi_repo.mark_reconciled(
                tenant_id=tenant_id,
                environment_id=environment_id,
                managed_integration_id=mi,
                result=str(view.result),
                observed_state_ref=view.observed_state_ref if had_evidence else None,
                at=instant,
            )
            summary["reconcile_results"][mi] = _summary_entry(view)

            if view.result != "actionable_drift":
                continue

            # ── plan the drift (§32 step 12, §35 guards) ──────────────────
            candidate = build_plan(
                managed_integration_ref=mi,
                tenant_id=tenant_id,
                environment_id=environment_id,
                desired_revision=view.desired_revision,
                observed_revision=view.observed_revision,
                reconcile_sequence=view.reconcile_id,
                drift=view.drift,
                initiator=_SCHEDULER_ACTOR,
                integration_kind=str(row["integration_kind"]),
                source_origin=str(row["source_origin"]),
                now=instant,
            )
            if candidate is None:
                # No deterministic remediation; the drift stays surfaced by
                # the persisted reconcile run (review/action, not silent skip).
                continue
            planned = with_status(candidate, "planned", now=instant)
            await get_change_set_repository().create(planned)
            summary["plans_created"].append(planned.changeset_id)
            if not planned.risk.automation_allowed:
                # §39: no automation authority for this risk class — the plan
                # rests at ``planned`` for the operator surface; no execution.
                continue

            # ── govern execution (§34/§39/§21) ─────────────────────────────
            lkg = await get_last_known_good_repository().get_for_integration(
                tenant_id, environment_id, mi
            )
            target = TargetSnapshot(
                managed_integration_ref=mi,
                desired_state_ref=row.get("desired_state_ref") or None,
                last_known_good_ref=str(lkg["lkg_id"]) if lkg else None,
            )
            outcome = await run_changeset(
                planned,
                target=target,
                current_desired_revision=view.desired_revision,
                current_observed_revision=view.observed_revision,
                actor=_SCHEDULER_ACTOR,
                now=instant,
                registry=registry,
            )
            summary["execution_outcomes"].append(_outcome_entry(mi, outcome))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one row must not kill the sweep
            summary["errors"].append(f"{mi}: {type(exc).__name__}: {exc}")
            logger.warning(
                "reconcile scheduler sweep failed for %s/%s/%s: %s",
                tenant_id,
                environment_id,
                mi,
                exc,
            )

    return summary


async def _scheduler_loop(
    *, registry: Optional[Any], interval_seconds: Optional[int]
) -> None:
    """One supervised scheduler loop: self-stopping, never overlapping passes.

    Flags and interval are re-read every pass (house pattern of
    ``provider_runtime/sync_worker.py``); ``CancelledError`` propagates so a
    supervisor can stop the loop; any other failure of one pass is logged and
    the loop continues after the interval.
    """
    from services.managed_integrations import flags
    from shared.logger.logger import get_logger

    logger = get_logger("aether.managed_integrations.scheduler")
    while True:
        if not (flags.enabled() and flags.scheduler_enabled()):
            # Self-stop: flags flipped off (or never on) between passes.
            return
        interval = (
            int(interval_seconds)
            if interval_seconds is not None
            else int(flags.scheduler_interval_seconds())
        )
        try:
            summary = await run_scheduler_pass(registry=registry)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad pass must not kill the loop
            logger.warning("reconcile scheduler pass failed: %s", exc)
        else:
            if summary.get("errors"):
                logger.warning(
                    "reconcile scheduler pass completed with %s error(s)",
                    len(summary["errors"]),
                )
            elif summary.get("plans_created") or summary.get("execution_outcomes"):
                logger.info(
                    "reconcile scheduler pass: %s plans, %s executions",
                    len(summary["plans_created"]),
                    len(summary["execution_outcomes"]),
                )
        await asyncio.sleep(max(0, interval))


def build_reconcile_scheduler_coro(
    *,
    registry: Optional[Any] = None,
    interval_seconds: Optional[int] = None,
) -> Callable[[], Awaitable[None]]:
    """Return a zero-arg factory; each call yields a FRESH scheduler coroutine.

    ``build_reconcile_scheduler_coro()`` returns the factory and
    ``build_reconcile_scheduler_coro()()`` returns one fresh loop coroutine —
    every invocation creates a new coroutine object, so a supervisor can start
    (and restart) the loop safely. ``registry`` (the §36 actuator registry to
    execute with) and ``interval_seconds`` (override of the
    ``scheduler_interval_seconds`` flag) are captured at build time.
    """
    return lambda: _scheduler_loop(
        registry=registry, interval_seconds=interval_seconds
    )
