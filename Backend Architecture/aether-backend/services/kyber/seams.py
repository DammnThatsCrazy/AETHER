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
)


def seams_for(module_prefix: str) -> tuple[Seam, ...]:
    """Every seam declared by callers under ``module_prefix``."""
    return tuple(s for s in SEAMS if s.caller.startswith(module_prefix))


__all__ = ["SEAMS", "Seam", "seams_for"]
