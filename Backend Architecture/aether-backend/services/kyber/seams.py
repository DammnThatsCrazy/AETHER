"""Declared cross-package call seams inside the Kyber plane.

Kyber is split into packages that must not import each other at module scope —
``identity`` needs to revoke sessions, ``devices`` needs to revoke sessions,
``access`` needs to resolve principals and devices, and the legacy
``kyber_operator`` routes need the scope service. Every one of those calls is a
function-level import guarded by ``try/except ImportError`` so that one plane
being unavailable degrades that plane rather than taking down the request.

That guard is correct, and it is also how two real defects shipped: a *wrong*
module path or symbol name is indistinguishable from an absent one, so a broken
integration reports success. Both escapees of the first Kyber release had this
exact shape:

* ``lifecycle`` imported ``devices.service.device_service`` (the module is
  ``devices.approvals`` and the singleton is ``device_approval_service``), so
  offboarding silently left devices approved and tenant scopes open;
* the access dependency called ``PolicyEngine.check_kyber_access`` with seven
  keyword arguments it does not accept, so Kyber access decisions never reached
  ``security_policy_decisions``.

Neither was caught by either side's own tests, because each side was internally
consistent. This module makes the seams *data*: every cross-package call is
declared once here, and ``scripts/validate_kyber_seams.py`` proves — by
importing and introspecting the real target — that each one still resolves and
still accepts the arguments its caller passes. A rename now fails the gate
instead of degrading in production.

Adding a seam is one entry. If you find yourself writing a function-level
import of another Kyber package and it is not declared here, that is the bug.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Seam:
    """One cross-package call, declared by the caller and proven by the gate."""

    #: Where the call is made from, for the failure message.
    caller: str
    #: Importable module holding the target.
    module: str
    #: Module-level singleton (or ``None`` when ``attribute`` is a module function).
    singleton: str | None
    #: Method or function invoked on the target.
    attribute: str
    #: Keyword arguments the caller passes. Every one must be accepted.
    keywords: tuple[str, ...] = ()
    #: Positional arity the caller relies on (excluding ``self``).
    positional: int = 0
    #: Why this seam exists, for reviewers.
    why: str = ""
    #: True when the caller tolerates the plane being absent. Even then the
    #: target must resolve when the module IS importable — that is the whole
    #: point: optional availability must never mask a typo.
    optional: bool = False


#: Every declared cross-package seam in the Kyber plane.
SEAMS: tuple[Seam, ...] = (
    # ── identity.lifecycle → the three planes it revokes ─────────────────────
    Seam(
        caller="services.kyber.identity.lifecycle.revoke_operator_access",
        module="services.kyber.sessions.service",
        singleton="session_service",
        attribute="revoke_for_operator",
        positional=1,
        keywords=("reason",),
        why="Offboarding must end every live session for the principal.",
        optional=True,
    ),
    Seam(
        caller="services.kyber.identity.lifecycle.revoke_operator_access",
        module="services.kyber.devices.approvals",
        singleton="device_approval_service",
        attribute="list_devices",
        positional=1,
        why="Offboarding revokes devices individually so each keeps its own "
            "approval event and audit record.",
        optional=True,
    ),
    Seam(
        caller="services.kyber.identity.lifecycle.revoke_operator_access",
        module="services.kyber.devices.approvals",
        singleton="device_approval_service",
        attribute="revoke_device",
        positional=1,
        keywords=("actor_id", "reason"),
        why="Offboarding must revoke every approved device.",
        optional=True,
    ),
    Seam(
        caller="services.kyber.identity.lifecycle.revoke_operator_access",
        module="services.kyber.access.scopes",
        singleton="access_scope_service",
        attribute="revoke_for_operator",
        positional=1,
        keywords=("reason",),
        why="An open tenant scope must not outlive the identity that opened it.",
        optional=True,
    ),
    # ── devices → sessions ───────────────────────────────────────────────────
    Seam(
        caller="services.kyber.devices.approvals.revoke_device",
        module="services.kyber.sessions.service",
        singleton="session_service",
        attribute="revoke_for_device",
        positional=1,
        keywords=("reason",),
        why="Revoking a device must terminate the sessions bound to it.",
        optional=True,
    ),
    # ── identity.routes → sessions ───────────────────────────────────────────
    Seam(
        caller="services.kyber.identity.routes.kyber_callback",
        module="services.kyber.sessions.service",
        singleton="session_service",
        attribute="create_session",
        keywords=(
            "operator_id", "google_subject", "device_id", "environment",
            "authentication_methods", "client_ip", "user_agent",
        ),
        why="The OIDC callback establishes the workforce session.",
        optional=True,
    ),
    Seam(
        caller="services.kyber.identity.routes.kyber_logout",
        module="services.kyber.sessions.service",
        singleton="session_service",
        attribute="revoke",
        positional=1,
        keywords=("reason",),
        why="Logout revokes the current session. Shipped once as revoke_session(), "
            "which does not exist — logout was a hard 500.",
        optional=True,
    ),
    # ── routes → the canonical authorization gate ────────────────────────────
    Seam(
        caller="services.kyber.identity.routes / services.kyber.devices.routes",
        module="services.kyber.access.dependencies",
        singleton=None,
        attribute="require_kyber_access",
        positional=1,
        keywords=("disclosure", "action_class", "tenant_scope"),
        why="Every Kyber route authorizes through this factory.",
    ),
    Seam(
        caller="services.kyber_operator.routes",
        module="services.kyber.access.dependencies",
        singleton=None,
        attribute="current_kyber_context",
        positional=1,
        why="The legacy tenant-entry shim binds a durable scope to the live "
            "workforce session.",
    ),
    # ── access → the shared governance engines (no second engine) ────────────
    Seam(
        caller="services.kyber.access.dependencies",
        module="services.security.policy_engine",
        singleton="policy_engine",
        attribute="check_kyber_access",
        keywords=(
            "actor_id", "operator_id", "session_id", "device_id", "capability",
            "action_class", "route_id", "environment", "target_tenant", "purpose",
            "requested_disclosure", "granted_disclosure", "allowed",
        ),
        why="Kyber decisions record through the existing PolicyEngine so they "
            "land in security_policy_decisions with a linked audit entry. "
            "Shipped once with seven kwargs the method does not accept.",
        optional=True,
    ),
    # ── access.emergency → the shared break-glass service ────────────────────
    # emergency_root is not a second emergency path. It is the existing
    # break-glass state machine — second-actor approval, expiry, tamper-evident
    # transitions — addressed at a reserved platform scope. That makes these
    # four calls the load-bearing seam of the emergency plane: if `approve`
    # drifted, Kyber would keep accepting approvals while the second-actor rule
    # stopped running, which is the entire control.
    Seam(
        caller="services.kyber.access.emergency.request_emergency_access",
        module="services.security.break_glass",
        singleton="break_glass_service",
        attribute="request",
        keywords=("tenant_id", "requested_by", "reason", "requested_scope", "window_hours"),
        why="An emergency-root request is a break-glass request at the reserved "
            "platform scope — never a parallel request table.",
    ),
    Seam(
        caller="services.kyber.access.emergency.approve_emergency_access",
        module="services.security.break_glass",
        singleton="break_glass_service",
        attribute="approve",
        keywords=("request_id", "approved_by"),
        why="Second-actor approval — including the refusal and audit of "
            "self-approval — is enforced there and never re-implemented here.",
    ),
    Seam(
        caller="services.kyber.access.emergency.has_active_emergency",
        module="services.security.break_glass",
        singleton="break_glass_service",
        attribute="has_active_grant",
        positional=2,
        why="Whether an operator holds live emergency authority, with stale "
            "grants expired as a side effect.",
    ),
    Seam(
        caller="services.kyber.access.emergency.active_emergency_requests",
        module="services.security.break_glass",
        singleton="break_glass_service",
        attribute="list_requests",
        keywords=("tenant_id", "limit"),
        why="The emergency surface lists only the reserved platform scope, so "
            "tenant break-glass never leaks onto it.",
    ),
    # ── every plane → the shared audit ledger ────────────────────────────────
    # Seven Kyber modules record through this one call. It is the single
    # highest-consequence seam in the plane: if the signature drifted, Kyber
    # would keep serving requests while silently writing no audit trail, and
    # nothing else would notice.
    Seam(
        caller="services.kyber.{access,devices,sessions}",
        module="services.security.audit_ledger",
        singleton="audit_ledger",
        attribute="record",
        keywords=(
            "actor_id", "actor_type", "event_type", "resource_type", "action",
            "outcome", "tenant_id", "resource_id", "policy_decision_id",
            "ip_address", "user_agent", "metadata",
        ),
        why="Every privileged Kyber action is audited through the existing "
            "tamper-evident ledger — never a parallel one.",
    ),
    # ── retention sweep → the shared audit ledger and policy registry ────────
    # The sweeper DELETES rows. Its two outward calls are both load-bearing:
    # the policy registry decides whether a table may be swept at all (and with
    # what window), and the ledger is the only record that a run happened. A
    # silent break in either would leave deletions unexplained, or — worse —
    # move the guard that keeps `legal`-class evidence out of reach.
    Seam(
        caller="services.kyber.retention.KyberRetentionSweeper._audit",
        module="services.security.audit_ledger",
        singleton="audit_ledger",
        attribute="record",
        keywords=(
            "actor_id", "actor_type", "event_type", "resource_type", "action",
            "outcome", "metadata",
        ),
        why="Each retention run writes one summary record to the shared "
            "tamper-evident ledger; a sweep with no audit trail is "
            "indistinguishable from data loss.",
        optional=True,
    ),
    Seam(
        caller="services.kyber.retention.KyberRetentionSweeper.policy",
        module="shared.storage.manager",
        singleton=None,
        attribute="policy_for",
        positional=2,
        why="The retention window and the short_lived/hard_delete guard both "
            "come from the policy registry — never a constant in the sweeper.",
    ),
    # ── identity.principals → the emergency guard ────────────────────────────
    Seam(
        caller="services.kyber.identity.principals.PrincipalService.bind_role",
        module="services.kyber.access.emergency",
        singleton=None,
        attribute="assert_not_emergency_template",
        positional=1,
        why="emergency_root must not be grantable as an ordinary standing role "
            "binding; break-glass authority reachable through the normal path "
            "would make the emergency path permanent.",
    ),
    # ── legacy operator routes → the durable scope plane ─────────────────────
    Seam(
        caller="services.kyber_operator.routes.enter_tenant",
        module="services.kyber.access.scopes",
        singleton="access_scope_service",
        attribute="open_scope",
        keywords=(
            "operator_id", "session_id", "device_id", "environment",
            "tenant_id", "purpose", "reason", "ttl_minutes",
        ),
        why="The legacy tenant-entry endpoint delegates to the durable scope "
            "plane; it previously wrote to a process-local dict nothing read.",
    ),
    Seam(
        caller="services.kyber_operator.routes.exit_tenant",
        module="services.kyber.access.scopes",
        singleton="access_scope_service",
        attribute="exit_scope",
        positional=1,
        keywords=("actor_id",),
        why="Exit closes the durable scope.",
    ),
    Seam(
        caller="services.kyber_operator.routes.exit_tenant",
        module="services.kyber.access.scopes",
        singleton="access_scope_service",
        attribute="get",
        positional=1,
        why="Exit resolves the durable scope before falling back to legacy state.",
    ),
    # ── ops plane → step-up ───────────────────────────────────────────────────
    # The ops plane resolves step-up once and hands it to the command lifecycle,
    # which gates action classes 4 and 5 on a live grant. If this read drifted,
    # the gate would resolve to a provider that answers nothing and every
    # high-impact command would either refuse forever or — depending on how the
    # caller reads a missing answer — stop being gated at all. Neither failure
    # announces itself, which is why the seam is declared rather than trusted.
    Seam(
        caller="services.kyber.ops.containment._resolve_ops_providers",
        module="services.kyber.sessions.step_up",
        singleton="step_up_service",
        attribute="active_grant",
        positional=1,
        why="Class 4/5 commands require a live step-up grant; this is the read "
            "that decides whether one exists.",
    ),
    # ── graph projector → the append-only mutation ledger ─────────────────────
    # The Kyber Graph is a projection with exactly one input. If this read
    # drifted — renamed, or its `limit`/`aggregate_id` keywords changed — the
    # projector would keep running, keep advancing nothing, and keep reporting
    # healthy empty batches, while the operational graph quietly froze at
    # whatever it had already built. A frozen graph that still answers is the
    # worst outcome available here, so the seam is declared even though the
    # target lives outside services.* and is not covered by the import scan.
    Seam(
        caller="services.kyber.graph.projector.KyberGraphProjector._fetch",
        module="repositories.graph_mutation_ledger",
        singleton="GraphMutationLedgerRepository",
        attribute="list_records",
        positional=1,
        keywords=("aggregate_id", "limit", "since_offset"),
        why="The graph projector's only input is the tenant's mutation ledger, "
            "read in ledger order so the offset it stores means something. "
            "`since_offset` is pinned because without it the projector must "
            "re-read every consumed row to reach one fresh one, and a consumer "
            "past its read window stalls permanently while still reporting "
            "healthy empty batches.",
    ),
)


def seams_for(module_prefix: str) -> tuple[Seam, ...]:
    """Every seam declared by callers under ``module_prefix``."""
    return tuple(s for s in SEAMS if s.caller.startswith(module_prefix))


__all__ = ["SEAMS", "Seam", "seams_for"]
