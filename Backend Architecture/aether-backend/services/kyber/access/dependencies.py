"""The single authorization entry point for every Kyber route.

There is exactly one place where a Kyber request is authorized, and this is it.
Routes declare what they need — a capability, a disclosure level, an action
class, whether a tenant scope is required — and this module decides. Handlers
never re-derive authority, and the frontend never derives it at all.

The evaluation order is fixed and every step fails closed:

===  ==============================================================  =========================
 #   Check                                                           Denial
===  ==============================================================  =========================
 1   Session handle present, live, not idle-expired, not replayed     ``no_session`` /
                                                                      ``session_expired`` /
                                                                      ``session_revoked`` /
                                                                      ``session_restricted``
 2   Principal resolves, is ``active`` and ``kyber_enabled``          ``principal_unknown`` /
                                                                      ``principal_inactive``
 3   Directory record is fresh                                        ``directory_stale``
 4   Device resolves, is usable, and matches the session binding      ``device_unapproved`` /
                                                                      ``device_revoked`` /
                                                                      ``device_mismatch``
 5   Route classification (injected ``RoutePolicy`` or derived)       —
 6   Capability held; a live ``deny`` grant always wins               ``capability_missing``
 7   Environment allowed by every bound role template                 ``environment_not_allowed``
 8   Requested action class within the principal's ceiling            ``action_class_exceeded``
 9   Tenant scope resolves and names the requested tenant             ``scope_missing`` /
                                                                      ``scope_expired`` /
                                                                      ``scope_tenant_mismatch``
10   Effective disclosure = min(role, capability, scope, requested)   ``disclosure_exceeded``
11   Fresh step-up when the capability or disclosure demands it       ``step_up_required``
12   Durable ``KyberAccessDecision`` written, context returned        —
===  ==============================================================  =========================

Two structural commitments:

*No second engine.* The allow/deny is recorded through the existing
``services.security.policy_engine.PolicyEngine`` so Kyber decisions land in the
same governance ledger as everything else. The ``kyber_access_decisions`` row
is the Kyber-specific detail hanging off that decision — it carries
``policy_decision_id`` — not a parallel audit trail.

*No implicit trust in a missing dependency.* The identity, device and proof
services are reached through :class:`AccessProviders`. When a provider cannot
be resolved, every authorization path **denies**. An unavailable verifier is
never read as a passing verifier.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from repositories.repos import BaseRepository
from shared.common.common import ForbiddenError, UnauthorizedError
from shared.logger.logger import get_logger, metrics

from ..sessions.cookies import read_session_token
from ..sessions.validation import validate_mutating_request
from .capabilities import (
    ACTION_CLASS_READ,
    SELF_CAPABILITY,
    STEP_UP_ACTION_CLASSES,
    Capability,
    get_capability,
)
from .contracts import (
    AccessScope,
    DenialReason,
    KyberAccessDecision,
    WorkforceSession,
)
from .disclosure import DisclosureLevel, effective_disclosure, requires_step_up
from .roles import ROLE_TEMPLATES, max_action_class_for, max_disclosure_for

logger = get_logger("aether.kyber.access")

TenantScopeMode = Literal["none", "optional", "required"]

#: Denials that mean "authenticate again", as opposed to "you may not".
_UNAUTHENTICATED_REASONS: frozenset[str] = frozenset(
    {"no_session", "session_expired", "session_revoked", "principal_unknown"}
)

#: Header a non-browser operator client may use to name the target tenant.
TENANT_HEADER_NAME = "X-Kyber-Tenant"

#: Cookie holding the opaque device grant, resolved by the device plane.
DEVICE_GRANT_COOKIE_NAME = "__Host-kyber_device"


# ── Provider indirection ─────────────────────────────────────────────────────


@dataclass
class AccessProviders:
    """The four services this module depends on, resolved indirectly.

    Every field defaults to ``None`` and ``None`` means *deny*. The indirection
    exists so the identity, device and session packages can be built in
    parallel without import-order coupling, and so tests can substitute fakes
    without patching module globals.
    """

    #: ``services.kyber.identity.principals.principal_service``
    principals: Any = None
    #: ``services.kyber.devices.approvals.device_approval_service``
    devices: Any = None
    #: ``services.kyber.identity.directory_sync.directory_sync_service``
    directory: Any = None
    #: ``services.kyber.devices.device_proof.device_proof_service``
    proof: Any = None

    def missing(self) -> list[str]:
        """Names of the providers that failed to resolve."""
        return [
            name
            for name in ("principals", "devices", "directory", "proof")
            if getattr(self, name) is None
        ]


_PROVIDER_SPECS: tuple[tuple[str, str, str], ...] = (
    ("principals", "services.kyber.identity.principals", "principal_service"),
    ("devices", "services.kyber.devices.approvals", "device_approval_service"),
    ("directory", "services.kyber.identity.directory_sync", "directory_sync_service"),
    ("proof", "services.kyber.devices.device_proof", "device_proof_service"),
)

_providers: Optional[AccessProviders] = None


def _resolve_providers() -> AccessProviders:
    resolved = AccessProviders()
    for attr, module_path, symbol in _PROVIDER_SPECS:
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            logger.warning(f"kyber: access provider {attr!r} unavailable ({module_path}): {exc}")
            continue
        setattr(resolved, attr, getattr(module, symbol, None))
    return resolved


def get_providers() -> AccessProviders:
    """The resolved provider set, imported lazily and cached.

    Import failures are not errors here — they are recorded and turned into
    denials at decision time, so a partially-deployed Kyber refuses requests
    instead of failing to start.
    """
    global _providers
    if _providers is None:
        _providers = _resolve_providers()
        missing = _providers.missing()
        if missing:
            logger.warning(f"kyber: authorization will deny; providers missing: {missing}")
    return _providers


def set_providers(providers: AccessProviders) -> None:
    """Install a provider set. The seam tests use to supply fakes."""
    global _providers
    _providers = providers


def reset_providers() -> None:
    """Forget the cached provider set so the next call re-resolves."""
    global _providers
    _providers = None


# ── Context and decisions ────────────────────────────────────────────────────


@dataclass
class KyberAccessContext:
    """Everything the backend decided about one request.

    Handlers read this instead of re-deriving authority. In particular
    ``granted_disclosure`` is the level the response must be rendered at — it
    is already the minimum across role, capability, scope and request.
    """

    session: WorkforceSession
    principal: Any
    device: Any = None
    role_template_ids: list[str] = field(default_factory=list)
    capabilities: frozenset[str] = frozenset()
    granted_disclosure: DisclosureLevel = DisclosureLevel.D0_PLATFORM_TOPOLOGY
    scope: Optional[AccessScope] = None
    environment: str = "local"
    decision: Optional[KyberAccessDecision] = None
    capability: Optional[Capability] = None
    tenant_id: Optional[str] = None
    stepped_up: bool = False

    @property
    def operator_id(self) -> str:
        return self.session.operator_id

    @property
    def device_id(self) -> Optional[str]:
        return self.session.device_id

    def has_capability(self, capability_id: str) -> bool:
        """Whether the caller holds a capability, without a second lookup."""
        return capability_id in self.capabilities

    def masks_identifiers(self) -> bool:
        """Whether the response must mask tenant-identifying fields."""
        return self.granted_disclosure <= DisclosureLevel.D2_TENANT_MASKED


class KyberAccessDecisionRepository(BaseRepository):
    """JSONB store for ``kyber_access_decisions``."""

    def __init__(self) -> None:
        super().__init__("kyber_access_decisions")


_decisions = KyberAccessDecisionRepository()


@dataclass(frozen=True)
class _AccessSpec:
    """What a route declared it needs."""

    capability_id: Optional[str] = None
    disclosure: Optional[DisclosureLevel] = None
    action_class: int = ACTION_CLASS_READ
    tenant_scope: TenantScopeMode = "none"
    presence_only: bool = False


# ── Request helpers ──────────────────────────────────────────────────────────


def _header(request: Any, name: str) -> Optional[str]:
    headers = getattr(request, "headers", None) or {}
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    return getter(name) or getter(name.lower())


def _client_ip(request: Any) -> Optional[str]:
    client = getattr(request, "client", None)
    return getattr(client, "host", None) if client is not None else None


def _requested_tenant(request: Any) -> Optional[str]:
    """The tenant the request names, from the path, query, header or state.

    Whatever this returns is an *assertion by the client*. It is only ever
    compared against the scope; it never grants anything.
    """
    for source in ("path_params", "query_params"):
        params = getattr(request, source, None) or {}
        getter = getattr(params, "get", None)
        if getter is not None:
            value = getter("tenant_id")
            if value:
                return str(value)
    header = _header(request, TENANT_HEADER_NAME)
    if header:
        return header
    state = getattr(request, "state", None)
    value = getattr(state, "tenant_id", None) if state is not None else None
    return str(value) if value else None


def _route_policy(request: Any) -> Any:
    """The ``RoutePolicy`` the security middleware attached, if any."""
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "route_policy", None)


def _route_id(request: Any) -> Optional[str]:
    policy = _route_policy(request)
    route_id = getattr(policy, "route_id", None)
    if route_id:
        return str(route_id)
    scope = getattr(request, "scope", None) or {}
    route = scope.get("route") if isinstance(scope, dict) else None
    return getattr(route, "path", None)


def _request_path(request: Any) -> Optional[str]:
    url = getattr(request, "url", None)
    path = getattr(url, "path", None)
    return str(path) if path else None


# ── The evaluator ────────────────────────────────────────────────────────────


class _Denied(Exception):
    """Internal control flow: a step failed, carrying its reason."""

    def __init__(self, reason: Optional[DenialReason], detail: str, *, code: Optional[str] = None):
        self.reason = reason
        self.detail = detail
        self.code = code
        super().__init__(detail)


async def _persist_decision(decision: KyberAccessDecision) -> None:
    try:
        await _decisions.insert(decision.decision_id, decision.model_dump())
    except Exception as exc:  # pragma: no cover - the decision must not 500 the route
        logger.error(f"kyber: failed to persist access decision {decision.decision_id}: {exc}")


async def _record_through_policy_engine(decision: KyberAccessDecision) -> Optional[str]:
    """Route the decision through the shared policy engine when it supports it.

    Worker D adds ``PolicyEngine.check_kyber_access``. Until it exists — or if
    its signature differs — this falls back to writing an audit-ledger entry
    directly, so a Kyber decision is never unrecorded.
    """
    try:
        from services.security.policy_engine import policy_engine
    except Exception as exc:  # pragma: no cover - security package unavailable
        logger.error(f"kyber: policy engine unavailable: {exc}")
        return None

    check = getattr(policy_engine, "check_kyber_access", None)
    if check is None:
        return None
    try:
        result = await check(
            actor_id=decision.operator_id or "unknown",
            actor_type="olympus_operator",
            capability_id=decision.capability_id,
            action=decision.action or "read",
            action_class=decision.action_class,
            resource_type=decision.resource_type or "kyber_route",
            resource_id=decision.resource_id,
            tenant_id=decision.tenant_id,
            environment=decision.environment,
            session_id=decision.session_id,
            device_id=decision.device_id,
            scope_id=decision.scope_id,
            allowed=decision.allowed,
            denial_reason=decision.denial_reason,
            requested_disclosure=decision.requested_disclosure,
            granted_disclosure=decision.granted_disclosure,
            step_up_required=decision.step_up_required,
        )
    except Exception as exc:
        logger.warning(f"kyber: policy engine kyber check unusable, falling back: {exc}")
        return None
    return getattr(result, "decision_id", None)


async def _audit_fallback(decision: KyberAccessDecision) -> None:
    from services.security.audit_ledger import audit_ledger

    await audit_ledger.record(
        actor_id=decision.operator_id or "unknown",
        actor_type="olympus_operator",
        event_type="kyber.access.decision",
        resource_type=decision.resource_type or "kyber_route",
        action=decision.action or "read",
        outcome="allowed" if decision.allowed else "blocked",
        tenant_id=decision.tenant_id,
        resource_id=decision.resource_id or decision.route_id,
        policy_decision_id=decision.policy_decision_id,
        metadata={
            "capability_id": decision.capability_id,
            "denial_reason": decision.denial_reason,
            "action_class": decision.action_class,
            "requested_disclosure": decision.requested_disclosure,
            "granted_disclosure": decision.granted_disclosure,
            "scope_id": decision.scope_id,
            "session_id": decision.session_id,
            "device_id": decision.device_id,
            "environment": decision.environment,
            "step_up_required": decision.step_up_required,
        },
    )


async def _emit_decision(decision: KyberAccessDecision) -> KyberAccessDecision:
    """Record one decision everywhere it must appear.

    The governance ledger first (so ``policy_decision_id`` can be carried),
    then the durable Kyber row, then metrics. A failure to record never turns a
    deny into an allow — the caller has already decided by this point.
    """
    policy_decision_id = await _record_through_policy_engine(decision)
    if policy_decision_id:
        decision.policy_decision_id = policy_decision_id
    else:
        try:
            await _audit_fallback(decision)
        except Exception as exc:  # pragma: no cover - ledger unavailable
            logger.error(f"kyber: audit fallback failed for {decision.decision_id}: {exc}")

    await _persist_decision(decision)

    metrics.increment(
        "kyber_access_decision_total",
        labels={"allowed": str(decision.allowed).lower(), "capability": decision.capability_id or "-"},
    )
    if not decision.allowed:
        metrics.increment(
            "kyber_access_denied_total",
            labels={"reason": decision.denial_reason or (decision.metadata or {}).get("reason", "unknown")},
        )
    return decision


def _http_error(reason: Optional[str], detail: str) -> Exception:
    if reason in _UNAUTHENTICATED_REASONS:
        return UnauthorizedError(detail, details={"denial_reason": reason})
    return ForbiddenError(detail, details={"denial_reason": reason})


async def _evaluate(request: Any, spec: _AccessSpec, trace: dict[str, Any]) -> KyberAccessContext:
    """Run the ordered checks. Raises ``_Denied`` at the first failure.

    ``trace`` accumulates whatever was resolved before the failing step, so a
    denial still produces a decision row naming the operator, session, device
    and tenant involved. A denial that identifies nobody is not evidence.
    """
    providers = get_providers()
    environment = "local"
    session: Optional[WorkforceSession] = None
    principal: Any = None
    device: Any = None
    scope: Optional[AccessScope] = None
    template_ids: list[str] = []
    capabilities: frozenset[str] = frozenset()
    requested_tenant = _requested_tenant(request)
    capability = get_capability(spec.capability_id) if spec.capability_id else None
    granted = DisclosureLevel.D0_PLATFORM_TOPOLOGY
    stepped_up = False

    # 1 ── Session.
    from ..sessions.service import session_service

    raw_token = read_session_token(request)
    if not raw_token:
        raise _Denied("no_session", "No Kyber session")

    session, reason = await session_service.validate(
        raw_token,
        client_ip=_client_ip(request),
        user_agent=_header(request, "User-Agent"),
    )
    if session is None:
        raise _Denied(reason or "no_session", "Kyber session is not usable")
    environment = session.environment
    trace.update(
        {
            "operator_id": session.operator_id,
            "session_id": session.session_id,
            "device_id": session.device_id,
            "environment": environment,
        }
    )
    if reason == "session_restricted" and not spec.presence_only:
        raise _Denied(
            "session_restricted",
            "This session has presence access only; complete device authentication",
        )

    # Request-shape controls for mutating requests. A forged origin or a
    # missing CSRF token is a malformed request, not an authorization outcome,
    # so it carries no DenialReason.
    shape_failure = validate_mutating_request(request)
    if shape_failure is not None:
        raise _Denied(None, "Request rejected by Kyber request validation", code=shape_failure)

    # 2 ── Principal.
    if providers.principals is None:
        raise _Denied("principal_unknown", "Kyber identity service is unavailable")
    principal = await providers.principals.get_by_operator_id(session.operator_id)
    if principal is None:
        raise _Denied("principal_unknown", "No workforce principal for this session")
    if not getattr(principal, "is_active", False):
        raise _Denied("principal_inactive", "This workforce principal is not active")

    template_ids = list(
        await providers.principals.role_template_ids(session.operator_id, environment=environment)
    )
    role_ceiling = max_disclosure_for(template_ids)
    role_max_action = max_action_class_for(template_ids)
    privileged = role_max_action > ACTION_CLASS_READ or role_ceiling >= DisclosureLevel.D2_TENANT_MASKED

    if not spec.presence_only:
        # 3 ── Directory freshness. A stale directory record means Kyber cannot
        # confirm the person is still employed; privileged authority is
        # withdrawn until the reconciliation catches up.
        if providers.directory is None:
            raise _Denied("directory_stale", "Kyber directory reconciliation is unavailable")
        fresh, stale_reason = await providers.directory.directory_freshness(session.operator_id)
        if not fresh and privileged:
            raise _Denied(
                "directory_stale",
                f"Directory record is stale ({stale_reason or 'unknown'})",
            )

        # 4 ── Device.
        if providers.devices is None:
            raise _Denied("device_unapproved", "Kyber device service is unavailable")
        device = await _resolve_device(request, session, providers)
        usable, device_reason = await providers.devices.is_usable(
            getattr(device, "device_id", None)
        )
        if not usable:
            denial: DenialReason = (
                "device_revoked" if "revok" in (device_reason or "").lower() else "device_unapproved"
            )
            raise _Denied(denial, f"Device is not usable ({device_reason or 'unknown'})")
        touch = getattr(providers.devices, "touch", None)
        if touch is not None:
            try:
                await touch(device.device_id)
            except Exception as exc:  # pragma: no cover - telemetry, not authority
                logger.debug(f"kyber: device touch failed: {exc}")

    # 5 ── Route classification. When the security middleware attached a
    # RoutePolicy, its risk classification tightens what the decorator asked
    # for; it may never loosen it.
    policy = _route_policy(request)
    action_class = max(spec.action_class, ACTION_CLASS_READ)
    requested_disclosure = spec.disclosure
    if policy is not None and getattr(policy, "sensitive", False):
        requested_disclosure = requested_disclosure or DisclosureLevel.D2_TENANT_MASKED

    # 6 ── Capabilities.
    capabilities = frozenset(
        await providers.principals.effective_capabilities(
            session.operator_id, environment=environment
        )
    )
    if spec.capability_id is not None:
        if await _has_explicit_deny(providers, session.operator_id, spec.capability_id, environment):
            raise _Denied("capability_missing", "Capability is explicitly denied for this principal")
        if spec.capability_id not in capabilities:
            raise _Denied("capability_missing", "Capability not held")

    # 7 ── Environment.
    if not _environment_allowed(template_ids, principal, environment):
        raise _Denied("environment_not_allowed", "This role may not operate in this environment")

    # 8 ── Action class.
    if capability is not None:
        action_class = max(action_class, capability.action_class)
    if action_class > role_max_action:
        raise _Denied("action_class_exceeded", "Action class exceeds this role's ceiling")

    # 9 ── Tenant scope.
    if spec.tenant_scope != "none":
        needs_scope = spec.tenant_scope == "required" or requested_tenant is not None
        if needs_scope:
            if not requested_tenant:
                raise _Denied("scope_missing", "This route requires a tenant access scope")
            from .scopes import access_scope_service

            scope, scope_reason = await access_scope_service.resolve_for_tenant(
                session.session_id, requested_tenant
            )
            if scope is None:
                raise _Denied(scope_reason or "scope_missing", "No usable tenant access scope")
            trace["scope_id"] = scope.scope_id
            trace["purpose"] = scope.purpose
            if (
                scope.device_id
                and session.device_id
                and scope.device_id != session.device_id
            ):
                raise _Denied("device_mismatch", "Scope is bound to a different device")

    # 10 ── Disclosure. The minimum across every constraint in play.
    granted = effective_disclosure(
        role_ceiling,
        capability.max_disclosure if capability is not None else None,
        scope.disclosure_level if scope is not None else None,
        requested_disclosure,
    )
    if requested_disclosure is not None and granted < requested_disclosure:
        raise _Denied("disclosure_exceeded", "Requested disclosure exceeds the effective ceiling")

    # 11 ── Step-up.
    needs_step_up = (
        requires_step_up(granted)
        or action_class in STEP_UP_ACTION_CLASSES
        or (capability is not None and capability.requires_step_up)
    )
    if needs_step_up and not spec.presence_only:
        from ..sessions.step_up import step_up_service

        ok, step_reason = await step_up_service.require_fresh(
            session.session_id, capability_id=spec.capability_id
        )
        if not ok:
            raise _Denied(step_reason or "step_up_required", "A fresh step-up is required")
        stepped_up = True

    return KyberAccessContext(
        session=session,
        principal=principal,
        device=device,
        role_template_ids=template_ids,
        capabilities=capabilities,
        granted_disclosure=granted,
        scope=scope,
        environment=environment,
        capability=capability,
        tenant_id=requested_tenant,
        stepped_up=stepped_up,
    )


async def _resolve_device(request: Any, session: WorkforceSession, providers: AccessProviders) -> Any:
    """Resolve the device this request proved, and bind it to the session.

    The device grant cookie is authoritative when present. A grant that
    resolves to a different device than the session was opened on is a replay
    of a stolen handle on another machine, and is denied outright.
    """
    device = None
    cookies = getattr(request, "cookies", None) or {}
    grant_token = cookies.get(DEVICE_GRANT_COOKIE_NAME) if hasattr(cookies, "get") else None
    if grant_token:
        device = await providers.devices.resolve_by_grant(grant_token)
        if device is None:
            raise _Denied("device_unapproved", "Device grant did not resolve")
    elif session.device_id:
        device = await providers.devices.get_device(session.device_id)

    if device is None:
        raise _Denied("device_unapproved", "No trusted device for this session")

    device_id = getattr(device, "device_id", None)
    if session.device_id and device_id != session.device_id:
        raise _Denied("device_mismatch", "Device does not match the session binding")
    return device


async def _has_explicit_deny(
    providers: AccessProviders, operator_id: str, capability_id: str, environment: str
) -> bool:
    """Whether a live ``deny`` capability grant covers this capability.

    ``effective_capabilities`` already applies deny grants; this is a second,
    independent read so that a bug which drops a deny from the union cannot
    turn into an allow.
    """
    lookup = getattr(providers.principals, "active_capability_grants", None)
    if lookup is None:
        return False
    try:
        grants = await lookup(operator_id, environment=environment)
    except TypeError:
        try:
            grants = await lookup(operator_id)
        except Exception:  # pragma: no cover - provider shape mismatch
            return False
    except Exception:  # pragma: no cover - provider failure
        return False
    for grant in grants or ():
        if getattr(grant, "capability_id", None) != capability_id:
            continue
        if getattr(grant, "effect", "allow") == "deny":
            return True
    return False


def _environment_allowed(template_ids: list[str], principal: Any, environment: str) -> bool:
    """Every bound role template *and* the principal must allow the environment.

    An empty allow-list on either side means "no restriction". A non-empty one
    on any single template is enough to refuse — the templates intersect, they
    do not union.
    """
    for template_id in template_ids:
        template = ROLE_TEMPLATES.get(template_id)
        if template is None:
            continue
        allowed = template.allowed_environments
        if allowed and environment not in allowed:
            return False
    principal_allowed = getattr(principal, "allowed_environments", None) or ()
    if principal_allowed and environment not in principal_allowed:
        return False
    return True


def _build_decision(
    request: Any,
    spec: _AccessSpec,
    *,
    trace: dict[str, Any],
    reason: Optional[DenialReason],
    allowed: bool,
    extra: Optional[dict[str, Any]] = None,
) -> KyberAccessDecision:
    capability = get_capability(spec.capability_id) if spec.capability_id else None
    return KyberAccessDecision(
        operator_id=trace.get("operator_id"),
        session_id=trace.get("session_id"),
        device_id=trace.get("device_id"),
        route_id=_route_id(request),
        method=getattr(request, "method", None),
        path=_request_path(request),
        capability_id=spec.capability_id,
        action=capability.action if capability else "read",
        action_class=max(spec.action_class, capability.action_class if capability else 0),
        resource_type="kyber_route",
        resource_id=_route_id(request),
        environment=trace.get("environment"),
        tenant_id=trace.get("tenant_id") or _requested_tenant(request),
        scope_id=trace.get("scope_id"),
        purpose=trace.get("purpose"),
        requested_disclosure=int(spec.disclosure) if spec.disclosure is not None else None,
        granted_disclosure=trace.get("granted_disclosure"),
        allowed=allowed,
        denial_reason=reason,
        step_up_required=bool(trace.get("stepped_up")) or reason == "step_up_required",
        metadata=extra or {},
    )


async def resolve_access_context(
    request: Any,
    capability: Optional[str] = None,
    *,
    disclosure: Optional[DisclosureLevel] = None,
    action_class: int = ACTION_CLASS_READ,
    tenant_scope: TenantScopeMode = "none",
    presence_only: bool = False,
) -> KyberAccessContext:
    """Authorize a request imperatively and return its context.

    The same evaluation the dependency runs, for callers that cannot use
    FastAPI's dependency injection (background tasks, WebSocket handshakes,
    nested authorization inside a handler). Raises
    :class:`~shared.common.common.UnauthorizedError` or
    :class:`~shared.common.common.ForbiddenError` on denial, having already
    written the decision.
    """
    spec = _AccessSpec(
        capability_id=capability,
        disclosure=disclosure,
        action_class=action_class,
        tenant_scope=tenant_scope,
        presence_only=presence_only,
    )
    trace: dict[str, Any] = {"tenant_id": _requested_tenant(request)}
    try:
        context = await _evaluate(request, spec, trace)
    except _Denied as denied:
        decision = _build_decision(
            request,
            spec,
            trace=trace,
            reason=denied.reason,
            allowed=False,
            extra={"reason": denied.code or denied.reason or "denied", "detail": denied.detail},
        )
        await _emit_decision(decision)
        logger.warning(
            f"kyber: access denied reason={denied.reason or denied.code} "
            f"capability={capability} path={_request_path(request)}"
        )
        raise _http_error(denied.reason or denied.code, denied.detail) from None

    trace["granted_disclosure"] = int(context.granted_disclosure)
    trace["stepped_up"] = context.stepped_up
    decision = _build_decision(request, spec, trace=trace, reason=None, allowed=True)
    context.decision = await _emit_decision(decision)

    state = getattr(request, "state", None)
    if state is not None:
        try:
            state.kyber_context = context
        except Exception:  # pragma: no cover - exotic request objects
            pass
    return context


def require_kyber_access(
    capability: Optional[str] = None,
    *,
    disclosure: Optional[DisclosureLevel] = None,
    action_class: int = ACTION_CLASS_READ,
    tenant_scope: TenantScopeMode = "none",
) -> Callable[..., Any]:
    """Build the FastAPI dependency that authorizes a Kyber route.

    Args:
        capability: The capability id the route needs, or ``None`` for a route
            that only asserts a disclosure level.
        disclosure: The level the route intends to reveal. The caller is
            granted the minimum of this and every other ceiling; asking for
            more than the ceiling allows is a denial, not a silent downgrade.
        action_class: 0 read … 5 fleet-destructive. Anything at or above
            ``ACTION_CLASS_HIGH_IMPACT`` demands a fresh step-up.
        tenant_scope: ``"required"`` when the route always names one tenant,
            ``"optional"`` when it may, ``"none"`` for aggregate routes.

    Returns:
        An async dependency yielding a :class:`KyberAccessContext`, also
        stashed on ``request.state.kyber_context``.
    """

    async def _dependency(request: Any) -> KyberAccessContext:
        return await resolve_access_context(
            request,
            capability,
            disclosure=disclosure,
            action_class=action_class,
            tenant_scope=tenant_scope,
        )

    _dependency.__name__ = f"require_kyber_access[{capability or 'any'}]"
    _dependency.__kyber_capability__ = capability  # type: ignore[attr-defined]
    _dependency.__kyber_action_class__ = action_class  # type: ignore[attr-defined]
    _dependency.__kyber_tenant_scope__ = tenant_scope  # type: ignore[attr-defined]
    try:  # FastAPI needs the annotation to inject the request object.
        from fastapi import Request

        _dependency.__annotations__["request"] = Request
    except Exception:  # pragma: no cover - FastAPI always present in the app
        pass
    return _dependency


def require_kyber_presence() -> Callable[..., Any]:
    """Dependency for presence-only routes.

    A presence session opens the console and shows low-risk aggregate health.
    It reaches D0 topology and nothing else: no tenant detail, no evidence, no
    commands, no exports, no workforce administration. Device and directory
    checks are skipped because a presence session asserts no authority that
    would depend on them.
    """

    async def _dependency(request: Any) -> KyberAccessContext:
        return await resolve_access_context(
            request,
            SELF_CAPABILITY,
            disclosure=DisclosureLevel.D0_PLATFORM_TOPOLOGY,
            action_class=ACTION_CLASS_READ,
            tenant_scope="none",
            presence_only=True,
        )

    _dependency.__name__ = "require_kyber_presence"
    try:
        from fastapi import Request

        _dependency.__annotations__["request"] = Request
    except Exception:  # pragma: no cover
        pass
    return _dependency


def current_kyber_context(request: Any) -> Optional[KyberAccessContext]:
    """Read the context the dependency stashed on ``request.state``."""
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "kyber_context", None)


def require_kyber_context(request: Any) -> KyberAccessContext:
    """Read the stashed context, raising when the route was not guarded."""
    context = current_kyber_context(request)
    if context is None:
        raise ForbiddenError("This route was not authorized by Kyber")
    return context


__all__ = [
    "DEVICE_GRANT_COOKIE_NAME",
    "TENANT_HEADER_NAME",
    "AccessProviders",
    "KyberAccessContext",
    "KyberAccessDecisionRepository",
    "current_kyber_context",
    "get_providers",
    "require_kyber_access",
    "require_kyber_context",
    "require_kyber_presence",
    "reset_providers",
    "resolve_access_context",
    "set_providers",
]
