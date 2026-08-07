"""Kyber mobile action-adapter — a READ-ONLY action-availability digest (M6a).

The governed command lifecycle already lives at ``/v1/kyber/ops/commands/*``
(request → dry-run → approve → execute → verify, with ``_authorize_command``
nested authorization per spec). This surface REUSES that plane and never
duplicates it: there is **no second command plane**, no generic mutation
channel, and no endpoint that names an arbitrary action.

``GET /v1/kyber/mobile/actions`` is strictly read-only. It reports what a
governed action *exists for*, which capability that action would require, and
whether step-up is fresh. It performs no mutations and dispatches nothing — the
digest is an availability pointer, not a trigger.

Everything is composed from the OWNING services (prohibited-duplicate ledger,
decision-log D12):

* exception queue  -> ``services.kyber.ops.exceptions.exception_service.queue``
* open commands    -> ``services.kyber.ops.commands.command_service.list_commands``
* session step-up  -> ``services.kyber.sessions.step_up.step_up_service``

The adapter never re-derives priority / verification / correlation logic; owning-
service values pass through bounded and redacted only. Wire fields are snake_case
(decision-log D6). ``MobileActionDigest`` accepts injected collaborators so unit
tests exercise it with fakes (no DB); production defaults are resolved lazily at
call time rather than cached, so monkeypatching the owning-service singletons —
the established test seam — stays effective across calls on the module-level
singleton.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends

from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import get_logger

from ..access.capabilities import (
    ACTION_CLASS_ANNOTATE,
    ACTION_CLASS_FLEET_DESTRUCTIVE,
    ACTION_CLASS_HIGH_IMPACT,
    ACTION_CLASS_RECOMPUTE,
    ACTION_CLASS_RETRY,
    ACTION_CLASS_READ,
    STEP_UP_ACTION_CLASSES,
)
from ..access.disclosure import DisclosureLevel
from .contracts import now_iso
from .registry import get_command_spec

logger = get_logger("aether.kyber.ops.mobile_actions")

mobile_actions_router = APIRouter(
    prefix="/v1/kyber/mobile/actions", tags=["Kyber Mobile Actions"]
)

#: The capability the ops ``/v1/kyber/ops/commands`` routes gate on (M8-D3).
#: The digest surfaces the SAME open-command rows, so it must sit behind the
#: same authorization + disclosure declaration — never the low-bar
#: ``kyber.workforce.self.read``. Mirrors ``routes.AUDIT_READ``.
AUDIT_READ = "kyber.audit.read"

# ── Tier vocabulary ──────────────────────────────────────────────────────────
# tier0 = act now (critical_now exceptions + open high-impact/fleet-destructive
#         commands), tier1 = needs_action exceptions + other open commands,
# tier2 = watch, tier3 = informational. This is a presentational grouping of the
# owning services' own buckets/statuses — never a new ranking engine.

TIER_ORDER: tuple[str, ...] = ("tier0", "tier1", "tier2", "tier3")

#: Command statuses surfaced on each command tier. tier0 claims the high-impact
#: commands that are still an open decision first; the "other open commands" the
#: digest surfaces are the unsettled set that is not already on tier0.
_TIER0_COMMAND_STATUSES: frozenset[str] = frozenset(
    {"approved", "requested", "awaiting_approval"}
)
_TIER1_COMMAND_STATUSES: frozenset[str] = frozenset(
    {"requested", "awaiting_approval", "approved", "dry_run_complete"}
)

#: The governed capabilities an exception transition needs, by exception status
#: (mirrors the capability the ops routes actually authorize with).
INCIDENT_MANAGE = "kyber.incident.manage"
INCIDENT_CLOSE = "kyber.incident.close"

#: Presentational severity label for a command's action class — the capability
#: vocabulary from ``services/kyber/access/capabilities.py`` (0 read … 5 fleet).
_ACTION_CLASS_LABELS: dict[int, str] = {
    ACTION_CLASS_READ: "read",
    ACTION_CLASS_ANNOTATE: "annotate",
    ACTION_CLASS_RETRY: "retry",
    ACTION_CLASS_RECOMPUTE: "recompute",
    ACTION_CLASS_HIGH_IMPACT: "high_impact",
    ACTION_CLASS_FLEET_DESTRUCTIVE: "fleet_destructive",
}

#: Representative command capability per action class, used only when a command
#: row carries no ``capability_id`` and its ``command_type`` is not registered.
_COMMAND_CAPABILITY_BY_ACTION_CLASS: dict[int, str] = {
    ACTION_CLASS_RETRY: "kyber.command.retry",
    ACTION_CLASS_RECOMPUTE: "kyber.command.recompute",
    ACTION_CLASS_HIGH_IMPACT: "kyber.command.pause",
    ACTION_CLASS_FLEET_DESTRUCTIVE: "kyber.command.kill_switch",
}


# ── Availability-record projection helpers ───────────────────────────────────

def _exception_available_action(exc: dict) -> str:
    """The governed exception transition the status points at (presentational)."""
    status = exc.get("status") or "open"
    if status in ("acknowledged", "in_progress"):
        return "resolve"
    if status == "open":
        return "acknowledge"
    return "suppress"


def _exception_capability(exc: dict) -> str:
    """The capability a governed exception transition would require."""
    status = exc.get("status") or "open"
    return INCIDENT_CLOSE if status in ("resolved", "suppressed") else INCIDENT_MANAGE


def _project_exception(exc: dict, *, step_up_fresh: bool) -> dict:
    """One bounded, redacted availability record for an exception.

    Exceptions authorise annotate/close work (action class 1) through
    ``kyber.incident.manage`` / ``kyber.incident.close`` — never high-impact, so
    ``requires_step_up`` is always False here; the field is still carried so the
    item shape is uniform across kinds.
    """
    action_class = ACTION_CLASS_ANNOTATE
    return {
        "kind": "exception",
        "id": exc.get("exception_id"),
        "title": exc.get("title"),
        "severity": exc.get("severity"),
        "status": exc.get("status"),
        "action_class": action_class,
        "available_action": _exception_available_action(exc),
        "capability_id": _exception_capability(exc),
        "requires_step_up": action_class in STEP_UP_ACTION_CLASSES and not step_up_fresh,
        "priority_score": float(exc.get("priority_score") or 0.0),
        "signal_count": int(exc.get("signal_count") or 0),
        "last_seen_at": exc.get("last_seen_at"),
    }


def _command_available_action(row: dict) -> str:
    """The next governed lifecycle step, as a READ-ONLY label.

    Presentational only — this digest never invokes the action. An executed-but-
    unverified command points at ``verify``; a high-impact open command points at
    ``approve``; anything else is ``execute``.
    """
    if row.get("status") == "executed_unverified":
        return "verify"
    if row.get("action_class", 0) >= ACTION_CLASS_HIGH_IMPACT:
        return "approve"
    return "execute"


def _command_capability(row: dict) -> str:
    """The capability a governed action on this command would require.

    Prefers the command's own carried capability, then the registered spec's
    capability (the registry is the owning source), then a representative
    ``kyber.command.*`` capability for the action class.
    """
    carried = row.get("capability_id")
    if carried:
        return carried
    spec = get_command_spec(str(row.get("command_type") or ""))
    if spec is not None:
        return spec.capability_id
    return _COMMAND_CAPABILITY_BY_ACTION_CLASS.get(
        int(row.get("action_class") or 0), "kyber.command.retry"
    )


def _command_priority(row: dict) -> float:
    """Compose an already-computed blast-radius value; never re-derive it."""
    blast = row.get("blast_radius")
    if isinstance(blast, dict):
        for key in ("priority_score", "impact_score", "severity", "confidence"):
            value = blast.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def _project_command(row: dict, *, step_up_fresh: bool) -> dict:
    """One bounded, redacted availability record for a command."""
    action_class = int(row.get("action_class") or 0)
    return {
        "kind": "command",
        "id": row.get("command_id"),
        "title": row.get("command_type"),
        "severity": _ACTION_CLASS_LABELS.get(action_class, str(action_class)),
        "status": row.get("status"),
        "action_class": action_class,
        "available_action": _command_available_action(row),
        "capability_id": _command_capability(row),
        "requires_step_up": action_class in STEP_UP_ACTION_CLASSES and not step_up_fresh,
        "priority_score": _command_priority(row),
        "signal_count": 0,
        "last_seen_at": row.get("updated_at"),
    }


# ── Digest composition service ───────────────────────────────────────────────

class MobileActionDigest:
    """Compose the action-availability digest from the owning services.

    Collaborators are injected for tests; ``None`` resolves the production
    defaults to the SAME owning-service components the canonical ops routes use.
    Production defaults are resolved at call time rather than cached so that
    monkeypatching the owning-service singletons (the established test seam)
    stays effective across calls on a shared instance.
    """

    def __init__(
        self,
        *,
        exception_queue: Any = None,
        command_list: Any = None,
        step_up_fresh: Any = None,
        step_up_active_grant: Any = None,
    ) -> None:
        self._exception_queue = exception_queue
        self._command_list = command_list
        self._step_up_fresh = step_up_fresh
        self._step_up_active_grant = step_up_active_grant

    # ── owning-service resolvers (lazy production defaults, call-time) ───────

    async def _queue(self) -> dict:
        if self._exception_queue is not None:
            return await self._exception_queue()
        from services.kyber.ops.exceptions import exception_service

        return await exception_service.queue()

    async def _commands(self, tenant_id: Optional[str] = None) -> list:
        """The open command rows for the digest, bound to ``tenant_id``.

        ``tenant_id`` is the operator's resolved scope tenant (M8-D3): scoped
        operators see only their own tenant's commands; ``None`` (unscoped,
        behind the ``kyber.audit.read`` route gate) keeps the global list the
        ops routes expose. The bound value is passed to the OWNING service so
        the filter is applied where the rows are indexed — never a post-hoc
        strip of already-fetched rows.
        """
        if self._command_list is not None:
            return await self._command_list(tenant_id=tenant_id)
        from services.kyber.ops.commands import command_service

        return await command_service.list_commands(
            status="open", limit=200, tenant_id=tenant_id
        )

    async def _require_fresh(self, session_id: str) -> tuple[bool, Optional[str]]:
        if self._step_up_fresh is not None:
            return await self._step_up_fresh(session_id)
        from services.kyber.sessions.step_up import step_up_service

        return await step_up_service.require_fresh(session_id)

    async def _active_grant(self, session_id: str) -> Any:
        if self._step_up_active_grant is not None:
            return await self._step_up_active_grant(session_id)
        from services.kyber.sessions.step_up import step_up_service

        return await step_up_service.active_grant(session_id)

    # ── surface method ───────────────────────────────────────────────────────

    async def action_availability(self, *, context: Any) -> dict:
        """Compose the tiered availability digest for the authenticated operator.

        Operator identity comes from ``context`` (the ``KyberAccessContext`` the
        route dependency resolved), never from the request body or query.
        """
        queue = await self._queue()
        buckets = queue.get("buckets") or {}

        # M8-D3: the open-command list is bound to the operator's resolved
        # tenant scope. Unscoped (scope-less) operators pass the ``kyber.audit.read``
        # route gate and see the global list, exactly like the ops /commands routes.
        scope = getattr(context, "scope", None)
        scope_tenant_id = getattr(scope, "tenant_id", None) if scope is not None else None

        session_id = getattr(getattr(context, "session", None), "session_id", None)
        step_up_fresh, _denial = await self._require_fresh(session_id)

        grant = None
        if step_up_fresh:
            grant = await self._active_grant(session_id)

        tiers: dict[str, list[dict]] = {name: [] for name in TIER_ORDER}

        for exc in buckets.get("critical_now", []):
            tiers["tier0"].append(_project_exception(exc, step_up_fresh=step_up_fresh))
        for exc in buckets.get("needs_action", []):
            tiers["tier1"].append(_project_exception(exc, step_up_fresh=step_up_fresh))
        for exc in buckets.get("watch", []):
            tiers["tier2"].append(_project_exception(exc, step_up_fresh=step_up_fresh))
        for exc in buckets.get("informational", []):
            tiers["tier3"].append(_project_exception(exc, step_up_fresh=step_up_fresh))

        for row in await self._commands(tenant_id=scope_tenant_id):
            action_class = int(row.get("action_class") or 0)
            status = row.get("status")
            if action_class >= ACTION_CLASS_HIGH_IMPACT and status in _TIER0_COMMAND_STATUSES:
                tiers["tier0"].append(_project_command(row, step_up_fresh=step_up_fresh))
            elif status in _TIER1_COMMAND_STATUSES:
                tiers["tier1"].append(_project_command(row, step_up_fresh=step_up_fresh))
            # executing / executed_unverified are open but not surfaced here per
            # the digest tier rules — a presentational choice, not a state change.

        return {
            "tiers": tiers,
            "counts": {name: len(items) for name, items in tiers.items()},
            "step_up_required": not step_up_fresh,
            "step_up": {
                "fresh": step_up_fresh,
                "grant_id": grant.grant_id if grant is not None else None,
                "expires_at": grant.expires_at if grant is not None else None,
            },
            "generated_at": now_iso(),
        }


#: Module-level singleton (one digest endpoint, not a new subsystem).
_digest_service = MobileActionDigest()


def _require(capability: str, **kwargs: Any) -> Callable[..., Any]:
    """Build the Kyber access dependency, or a dependency that denies.

    A missing authorization module must never read as "no authorization
    required", so the fallback refuses rather than passing the request through —
    the same fail-closed pattern the ops routes use.
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only while the access plane is absent
        logger.error(
            f"kyber mobile actions dependency unavailable; routes will deny "
            f"capability={capability}"
        )

        async def _deny() -> None:
            raise ForbiddenError("Kyber access control is unavailable")

        return _deny
    return require_kyber_access(capability, **kwargs)


@mobile_actions_router.get("")
async def action_availability(
    context: Any = Depends(
        _require(
            AUDIT_READ,
            disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
            action_class=ACTION_CLASS_READ,
        )
    ),
) -> dict:
    """The action-availability digest for the authenticated operator.

    READ-ONLY. Composes the owning exception queue + open command list + session
    step-up state; performs no mutations and dispatches nothing. The governed
    command lifecycle remains at ``/v1/kyber/ops/commands/*`` — this surface only
    reports what a governed action exists for and whether step-up is fresh.

    The gate mirrors the ops ``/commands`` routes (``kyber.audit.read`` +
    D4 event-evidence disclosure + read action class) because the digest
    surfaces the same open-command rows. Open commands are further bound to the
    operator's resolved tenant scope (M8-D3).
    """
    data = await _digest_service.action_availability(context=context)
    return APIResponse(data=data).to_dict()


__all__ = ["MobileActionDigest", "action_availability", "mobile_actions_router"]
