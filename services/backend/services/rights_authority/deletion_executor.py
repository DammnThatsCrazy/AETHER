"""Aether — Rights Authority: retention DELETION EXECUTOR (blueprint §9 / §10).

The retention seam (``services.rights_authority.retention``) computes an expiry
and schedules a **pending** ``delete_at_expiry`` impact item, and
``services.rights_authority.deletion_adapters`` knows how to delete one
artifact. This module is the sweep that joins them: it reads pending retention
deletion rows, resolves the adapter for the row's ``component_type``, deletes
through it, and records what actually happened.

Doctrine: never silent retention, never fake completion, fail closed.

Enabling gates (ALL must hold, otherwise the row is left ``pending`` and nothing
is deleted — there is no partial or best-effort path):

1. **Rollout phase** — ``services.rights_authority.rollout`` must be in
   ``enforce``. ``off`` is inert; ``shadow``/``warn`` record and warn but never
   bind, and an irreversible deletion may not run in a phase that does not bind.
2. **Opt-in enable flag** — ``settings.rights_authority.
   deletion_executor_enabled`` (env ``RIGHTS_AUTHORITY_DELETION_EXECUTOR_ENABLED``,
   default **False**). Activation is always explicit.
3. **A present adapter** — the registry must serve the row's ``component_type``.
   A dimension with no real delete path stays ``pending`` and is reported as
   unsupported (:data:`~services.rights_authority.deletion_adapters.
   UNSUPPORTED_DIMENSION_REASONS`), never stubbed to a fake success.

Per-row safety preconditions (applied on top of the gates, also fail closed):

- **Due** — the scheduled retention expiry must have passed. The expiry is read
  from the row when it is carried structurally (``expires_at`` /
  ``retention_expiry`` / ``delete_after`` / ``due_at``) or from the documented
  retention reason prefix (``"retention expiry <ISO> for ..."``). When no due
  instant can be established the row is NOT deleted: deleting early destroys
  data that retention says must survive, so an unprovable due time is an
  ambiguity, and ambiguity fails closed.
- **Tenant scope** — the adapter must return a proof that the artifact sits in
  the impact's own tenant scope (see
  :meth:`~services.rights_authority.deletion_adapters.DeletionAdapter.
  validate_scope`). This is checked BEFORE any durable state is written.
- **Legal hold** — a tenant under an active storage legal hold is skipped
  entirely for that sweep. The hold check reuses the Data Exchange expire path's
  rule (``services.data_exchange.jobs_ops``): the holds store is consulted
  through ``StorageLifecycle.active_hold`` and an unhealthy holds store BLOCKS
  deletion rather than assuming no holds exist.

Crash safety (mirrors the Data Exchange expire path's "state flip before bytes"
ordering): the row is flipped to ``in_progress`` BEFORE the bytes are removed, so
a crash mid-deletion leaves a durable record that a deletion was in flight —
never bytes silently missing under a row that still advertises them. It is then
flipped to ``complete`` only after the adapter reports the bytes gone. A delete
error flips it to ``blocked`` rather than leaving the claim standing, so the
durable record never claims a removal that did not happen, and a crash between
the claim and the delete is retried by the next sweep (``in_progress`` is swept
alongside ``pending``).

State tokens: the repository validates ``remediation_state`` against
``services.rights_authority.contracts.ALLOWED_REMEDIATION_STATES`` =
``{pending, in_progress, complete, blocked, unknown}``. Note that
``impact.REMEDIATION_STATES`` (the internal row vocabulary) also carries
``executed``/``superseded`` — those are NOT accepted by ``update_state``, so the
terminal token written here is ``complete``.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Optional

from shared.common.common import parse_event_time, utc_now
from shared.logger.logger import get_logger, metrics
from services.rights_authority import rollout as rollout_mod
from services.rights_authority.deletion_adapters import (
    DELETION_STATUS_ALREADY_ABSENT,
    DELETION_STATUS_DELETED,
    DeletionAdapterRegistry,
    deletion_adapter_registry,
)
from services.rights_authority.retention import RETENTION_SCHEDULED_DELETE_ACTION

logger = get_logger("aether.rights_irrl.deletion_executor")

# The retention delete action this executor sweeps. ``delete_at_expiry`` is the
# token ``retention.evaluate_retention`` stamps on a scheduled deletion, so it is
# the only action this sweep owns. The destructive lifecycle verbs
# (delete/hard_delete/tombstone) are NOT included: they are revocation orders,
# not retention expiry, and a caller that wants this executor to own them must
# say so explicitly via the ``actions=`` argument rather than inherit scope.
RETENTION_DELETION_ACTIONS: frozenset[str] = frozenset({RETENTION_SCHEDULED_DELETE_ACTION})

# Impact states this sweep will act on. ``unknown`` is deliberately excluded: it
# means the recorded state was not in the canonical vocabulary, and guessing its
# meaning for an irreversible operation is exactly what fail-closed forbids.
_SWEEPABLE_STATES: frozenset[str] = frozenset({"pending", "in_progress"})

# Remediation states written by this module (all three are in
# contracts.ALLOWED_REMEDIATION_STATES; ``executed`` is NOT one of them).
CLAIM_STATE = "in_progress"   # durable tombstone written BEFORE byte deletion
COMPLETE_STATE = "complete"   # written only after the adapter reports the bytes gone
BLOCKED_STATE = "blocked"     # delete failed/refused after the claim was taken

DEFAULT_SWEEP_LIMIT = 500
# Per-sweep outcome list is capped so a large sweep cannot produce an unbounded
# report; the counters stay exact.
_MAX_OUTCOMES = 200

# Structural fields a producer may carry the due instant on.
_DUE_FIELDS: tuple[str, ...] = ("expires_at", "retention_expiry", "delete_after", "due_at")

# The retention seam's documented reason prefix: ``_scheduled_delete_item``
# writes ``"retention expiry <ISO> for <artifact_ref> (...)"``.
_REASON_EXPIRY_RE = re.compile(r"^retention expiry\s+(?P<expiry>\S+)\s+for\b")

# Canonical reason tag for a decision to delete that could not be proven due.
# Absent-because-unproven is recorded, never silently treated as eligible.
_NO_DUE_INSTANT_REASON = "retention expiry unprovable on this row"


@dataclass(frozen=True)
class DeletionGateDecision:
    """Why a deletion may (or may not) run for one ``component_type``."""

    allowed: bool
    rollout_ok: bool
    enabled_ok: bool
    adapter_ok: bool
    rollout_mode: str
    reason: str


def _executor_enabled_by_settings() -> bool:
    """The explicit opt-in flag (``RIGHTS_AUTHORITY_DELETION_EXECUTOR_ENABLED``).

    Read at call time, never cached: an operator turning the flag off must stop
    the next sweep, not the next process. A missing settings group is ``False``
    (fail closed), never ``True``.
    """
    from config.settings import settings  # lazy — avoids import cycles

    group = getattr(settings, "rights_authority", None)
    if group is None:  # pragma: no cover — settings group is always present
        return False
    return bool(getattr(group, "deletion_executor_enabled", False))


def deletion_gates(
    component_type: Optional[str],
    *,
    registry: Optional[DeletionAdapterRegistry] = None,
) -> DeletionGateDecision:
    """Evaluate the three enabling gates for one cascade dimension.

    All three are required; the returned ``reason`` names the first that failed
    so a report or an operator can see exactly what is holding deletion back.
    """
    registry = registry if registry is not None else deletion_adapter_registry
    mode = rollout_mod.current_mode()
    rollout_ok = rollout_mod.enforce_denials()
    enabled_ok = _executor_enabled_by_settings()
    adapter_ok = registry.has_adapter(component_type)

    if not rollout_ok:
        reason = (
            f"rollout={mode.value} does not bind "
            "(deletion requires RIGHTS_AUTHORITY_ROLLOUT=enforce)"
        )
    elif not enabled_ok:
        reason = (
            "deletion executor not enabled "
            "(set RIGHTS_AUTHORITY_DELETION_EXECUTOR_ENABLED=true)"
        )
    elif not adapter_ok:
        unsupported = registry.unsupported_reason(component_type)
        reason = (
            f"no deletion adapter for component_type {component_type!r}"
            + (f": {unsupported}" if unsupported else "")
        )
    else:
        reason = ""

    return DeletionGateDecision(
        allowed=rollout_ok and enabled_ok and adapter_ok,
        rollout_ok=rollout_ok,
        enabled_ok=enabled_ok,
        adapter_ok=adapter_ok,
        rollout_mode=mode.value,
        reason=reason,
    )


def _coerce_instant(value: Any) -> Optional[datetime]:
    """Aware UTC instant from a datetime/ISO string; ``None`` when unusable.

    A naive ``datetime`` is refused rather than guessed into a zone (matching the
    retention seam's time-safety rule).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return None if value.tzinfo is None else value
    if not isinstance(value, str):
        return None
    return parse_event_time(value.strip())


def retention_due_instant(row: dict) -> Optional[datetime]:
    """The scheduled deletion instant recorded on an impact row, if provable.

    Structural fields win over the reason text; both are validated through the
    shared temporal parser. ``None`` means the row does not establish when the
    deletion became due — which the executor treats as NOT due (fail closed).
    """
    for field in _DUE_FIELDS:
        instant = _coerce_instant(row.get(field))
        if instant is not None:
            return instant
    match = _REASON_EXPIRY_RE.match(str(row.get("reason") or "").strip())
    if match is None:
        return None
    return _coerce_instant(match.group("expiry"))


async def _legal_hold_blocks(
    tenant_id: str,
    checker: Optional[Callable[[str], Awaitable[bool]]],
) -> bool:
    """Whether an active legal hold blocks deletion for ``tenant_id``.

    Mirrors ``services.data_exchange.jobs_ops._resolve_legal_hold_blocked``: an
    injected checker wins (DB-free tests), no pool (``AETHER_ENV=local``) means
    no ``storage_legal_holds`` table exists so nothing can be held, and a
    hold-store error BLOCKS deletion — retention must never conclude "no holds"
    from an unhealthy holds store.
    """
    if checker is not None:
        return bool(await checker(tenant_id))
    from repositories.repos import get_pool  # lazy — local seam

    pool = await get_pool()
    if pool is None:
        return False
    try:
        from services.data_exchange.retention import DATA_ARTIFACT_RESOURCE_TYPE
        from shared.storage.lifecycle import StorageLifecycle  # lazy — heavy

        hold = await StorageLifecycle().active_hold(
            tenant_id, DATA_ARTIFACT_RESOURCE_TYPE
        )
        return hold is not None
    except Exception as exc:  # noqa: BLE001 — fail closed on an unhealthy hold store
        logger.warning(
            "deletion legal-hold check failed tenant=%s -> blocking: %s", tenant_id, exc
        )
        return True


def _is_sweepable(row: dict, actions: frozenset[str]) -> bool:
    action = str(row.get("required_action") or "").strip().lower()
    if action not in actions:
        return False
    state = str(row.get("remediation_state") or "pending").strip().lower()
    return state in _SWEEPABLE_STATES


def _capped(outcomes: list[dict], outcome: dict) -> None:
    if len(outcomes) < _MAX_OUTCOMES:
        outcomes.append(outcome)


def _empty_totals() -> dict[str, int]:
    return {
        "rows_scanned": 0,
        "eligible": 0,
        "deleted": 0,
        "already_absent": 0,
        "gate_blocked": 0,
        "not_due": 0,
        "no_due_instant": 0,
        "held": 0,
        "refused_out_of_scope": 0,
        "blocked": 0,
        "state_skipped": 0,
        "dry_run_eligible": 0,
    }


async def sweep_pending_deletions(
    *,
    tenant_id: Optional[str] = None,
    limit: int = DEFAULT_SWEEP_LIMIT,
    actions: Optional[Iterable[str]] = None,
    registry: Optional[DeletionAdapterRegistry] = None,
    repo: Any = None,
    legal_hold_checker: Optional[Callable[[str], Awaitable[bool]]] = None,
    dry_run: bool = False,
    now: Any = None,
) -> dict:
    """Execute pending retention deletions, returning an honest report.

    Reads pending retention deletion impacts for ``tenant_id`` (or across
    tenants when omitted — each row is still acted on strictly within its OWN
    tenant, and its artifact ref must be provable in that tenant's scope), and
    for each row: applies the three enabling gates, the due/scope/legal-hold
    preconditions, then claims → deletes → completes the row.

    Nothing outside the gates is deleted, every row that could not be deleted
    stays in a state that still surfaces it, and the report counts what happened
    rather than what was attempted. ``dry_run=True`` performs the full
    evaluation and mutates nothing.
    """
    registry = registry if registry is not None else deletion_adapter_registry
    action_set = frozenset(
        str(a).strip().lower()
        for a in (actions if actions is not None else RETENTION_DELETION_ACTIONS)
    )
    if repo is None:
        from services.rights_authority.repositories import (  # lazy — test seam
            rights_impact_repository,
        )

        repo = rights_impact_repository

    now_utc = _coerce_instant(now) or utc_now()

    if tenant_id is not None:
        rows = await repo.list_pending(tenant_id, limit=limit)
    else:
        rows = await repo.list_pending(limit=limit)

    totals = _empty_totals()
    outcomes: list[dict] = []
    hold_cache: dict[str, bool] = {}
    gates: dict[str, dict] = {}

    for row in rows:
        totals["rows_scanned"] += 1
        impact_id = row.get("impact_id")
        component_type = str(row.get("component_type") or "")
        row_tenant = str(row.get("tenant_id") or "")

        if not _is_sweepable(row, action_set):
            totals["state_skipped"] += 1
            _capped(outcomes, {
                "impact_id": impact_id,
                "action": "skip",
                "reason": "not_a_retention_deletion_row",
            })
            continue

        decision = gates.get(component_type)
        if decision is None:
            gate = deletion_gates(component_type, registry=registry)
            decision = {
                "allowed": gate.allowed,
                "rollout_ok": gate.rollout_ok,
                "enabled_ok": gate.enabled_ok,
                "adapter_ok": gate.adapter_ok,
                "rollout_mode": gate.rollout_mode,
                "reason": gate.reason,
            }
            gates[component_type] = decision

        if not decision["allowed"]:
            # Row untouched: still pending, surfaced, and nothing was deleted.
            totals["gate_blocked"] += 1
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "skip",
                "reason": f"gate_blocked:{decision['reason']}",
            })
            continue

        adapter = registry.get(component_type)
        artifact_ref = row.get("artifact_ref")

        due_instant = retention_due_instant(row)
        if due_instant is None:
            totals["no_due_instant"] += 1
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "skip",
                "reason": f"not_due:{_NO_DUE_INSTANT_REASON}",
            })
            continue
        if due_instant > now_utc:
            totals["not_due"] += 1
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "skip",
                "reason": "not_due",
                "due_at": due_instant.isoformat(),
            })
            continue

        totals["eligible"] += 1

        if not row_tenant or not artifact_ref:
            # A row whose tenant or artifact is unknown cannot be scoped; nothing
            # is deleted and the row stays exactly as it was.
            totals["refused_out_of_scope"] += 1
            metrics.increment("rights_deletion_executor_refused_total")
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "refused",
                "reason": "missing_tenant_or_artifact_ref",
            })
            continue

        if row_tenant not in hold_cache:
            hold_cache[row_tenant] = await _legal_hold_blocks(row_tenant, legal_hold_checker)
        if hold_cache[row_tenant]:
            totals["held"] += 1
            metrics.increment("rights_deletion_executor_legal_hold_blocked_total")
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "skip",
                "reason": "legal_hold",
            })
            continue

        safe_ref = adapter.validate_scope(
            tenant_id=row_tenant, artifact_ref=str(artifact_ref)
        )
        if safe_ref is None:
            # Out-of-tenant / unprovable scope: never delete, and never move the
            # row to a state that would imply the artifact was handled.
            totals["refused_out_of_scope"] += 1
            metrics.increment("rights_deletion_executor_refused_total")
            logger.warning(
                "deletion refused: impact=%s tenant=%r artifact_ref=%r is not "
                "provably in tenant scope",
                impact_id,
                row_tenant,
                artifact_ref,
            )
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "refused",
                "reason": "out_of_tenant_scope",
            })
            continue

        if dry_run:
            totals["dry_run_eligible"] += 1
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "would_delete",
                "reason": "dry_run",
            })
            continue

        # Claim FIRST, bytes second (see the crash-safety note in the module
        # docstring): the durable record says a deletion is in flight before any
        # byte is removed, so a crash cannot leave bytes missing under a row that
        # still advertises them, and the next sweep retries the claim.
        await repo.update_state(impact_id, CLAIM_STATE)
        try:
            result = await adapter.delete(
                tenant_id=row_tenant, artifact_ref=str(artifact_ref)
            )
        except Exception as exc:  # noqa: BLE001 — surface, never claim completion
            await repo.update_state(impact_id, BLOCKED_STATE)
            totals["blocked"] += 1
            metrics.increment("rights_deletion_executor_error_total")
            logger.error(
                "deletion failed: impact=%s tenant=%s component_type=%s: %s",
                impact_id,
                row_tenant,
                component_type,
                exc,
            )
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": "blocked",
                "reason": f"delete_error:{type(exc).__name__}",
            })
            continue

        if result.deleted or result.status == DELETION_STATUS_ALREADY_ABSENT:
            await repo.update_state(impact_id, COMPLETE_STATE)
            if result.deleted:
                totals["deleted"] += 1
                metrics.increment("rights_deletion_executor_deleted_total")
            else:
                totals["already_absent"] += 1
            _capped(outcomes, {
                "impact_id": impact_id,
                "component_type": component_type,
                "action": result.status,
                "reason": result.reason,
                "evidence_refs": list(result.evidence_refs),
            })
            continue

        # The adapter refused after the claim (unreachable through this sweep,
        # which refuses first — kept because an adapter must never be able to
        # leave a row claiming a deletion that did not happen).
        await repo.update_state(impact_id, BLOCKED_STATE)
        totals["blocked"] += 1
        metrics.increment("rights_deletion_executor_refused_total")
        _capped(outcomes, {
            "impact_id": impact_id,
            "component_type": component_type,
            "action": "blocked",
            "reason": f"adapter_{result.status}:{result.reason}",
        })

    report = {
        "dry_run": bool(dry_run),
        "swept_at": now_utc.isoformat(),
        "tenant_id": tenant_id,
        "actions": sorted(action_set),
        "gates": gates,
        "totals": totals,
        "outcomes": outcomes,
    }
    if totals["deleted"] or totals["blocked"] or totals["refused_out_of_scope"]:
        logger.info(
            "rights deletion sweep complete: deleted=%d already_absent=%d blocked=%d "
            "refused=%d held=%d not_due=%d gate_blocked=%d (tenant=%s)",
            totals["deleted"],
            totals["already_absent"],
            totals["blocked"],
            totals["refused_out_of_scope"],
            totals["held"],
            totals["not_due"] + totals["no_due_instant"],
            totals["gate_blocked"],
            tenant_id or "all",
        )
    return report


def _sweep_interval_seconds() -> int:
    raw = os.getenv("RIGHTS_DELETION_EXECUTOR_INTERVAL_SECONDS", "3600").strip() or "3600"
    try:
        interval = int(raw)
    except ValueError:
        logger.warning(
            "invalid RIGHTS_DELETION_EXECUTOR_INTERVAL_SECONDS=%r; using 3600s", raw
        )
        return 3600
    return interval if interval > 0 else 3600


async def run_rights_deletion_sweep_loop(interval_seconds: Optional[int] = None) -> None:
    """Supervised periodic sweep: the executor's only production entry point.

    Re-reads the gates on every pass (the enable flag can be turned off without
    restarting the process, and the loop does nothing while any gate is closed)
    and never lets a failed sweep kill the loop.
    """
    interval = interval_seconds if interval_seconds is not None else _sweep_interval_seconds()
    logger.info("rights deletion executor started: interval=%ss", interval)
    while True:
        try:
            await sweep_pending_deletions()
        except Exception as exc:  # noqa: BLE001 — a sweep failure must not kill the loop
            logger.error("rights deletion sweep failed: %s", exc)
            metrics.increment("rights_deletion_executor_loop_error")
        await asyncio.sleep(interval)


def build_rights_deletion_executor_coro(interval_seconds: Optional[int] = None):
    """Fresh coroutine for the supervisor (one per start attempt)."""
    return run_rights_deletion_sweep_loop(interval_seconds=interval_seconds)


__all__ = [
    "BLOCKED_STATE",
    "CLAIM_STATE",
    "COMPLETE_STATE",
    "DEFAULT_SWEEP_LIMIT",
    "RETENTION_DELETION_ACTIONS",
    "DeletionGateDecision",
    "build_rights_deletion_executor_coro",
    "deletion_gates",
    "retention_due_instant",
    "run_rights_deletion_sweep_loop",
    "sweep_pending_deletions",
]
