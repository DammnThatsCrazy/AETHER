"""HTTP surface for Kyber workforce identity.

Everything authorization-related is resolved on the backend. The browser gets a
redirect to Google, an opaque session cookie, and a rendered view of the
authority the backend computed — never a token, never a claim set, never a role
list it could reinterpret.

The access gate is imported lazily inside :func:`_require` so this module stays
importable while the access dependency is developed alongside it. The fallback
when it is missing **denies**: an unmounted authorization layer must never read
as an open one.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from services.kyber.access.capabilities import SELF_CAPABILITY
from services.kyber.access.contracts import KyberPrincipalView
from services.kyber.access.disclosure import DisclosureLevel
from services.kyber.access.roles import (
    DEVICE_APPROVER_TEMPLATE_IDS,
    max_action_class_for,
    max_disclosure_for,
)
from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    UnauthorizedError,
)
from shared.logger.logger import get_logger, metrics

from .bootstrap import founder_bootstrap_service
from .invitations import invitation_service
from .lifecycle import offboard_principal
from .oidc import OidcError, get_oidc_client, oidc_transaction_store
from .principals import normalize_email, principal_service, record_authentication_event

logger = get_logger("aether.kyber.identity.routes")

router = APIRouter(prefix="/v1/kyber", tags=["Kyber Identity"])

WORKFORCE_MANAGE = "kyber.workforce.manage"
ROLE_MANAGE = "kyber.role.manage"

__all__ = ["router"]


# ── Authorization gate ────────────────────────────────────────────────────────

def _denying_dependency(capability: str) -> Callable[..., Any]:
    """Fallback gate used only when the access dependency is not importable."""

    async def _denied() -> None:
        logger.error(
            "kyber access dependency unavailable; denying request for "
            f"capability={capability}"
        )
        metrics.increment("kyber_access_gate_unavailable_total")
        raise ForbiddenError("Kyber access control is unavailable")

    return _denied


def _require(capability: str, **kw: Any) -> Callable[..., Any]:
    """Resolve the Kyber access dependency for one capability.

    Imported lazily: ``services.kyber.access.dependencies`` composes sessions,
    devices and scopes, all of which import this package's services.
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only before the gate is mounted
        return _denying_dependency(capability)
    return require_kyber_access(capability, **kw)


def _ctx_get(context: Any, *names: str, default: Any = None) -> Any:
    """Read a field from the access context without depending on its class."""
    for name in names:
        if context is None:
            break
        if isinstance(context, dict) and name in context:
            return context[name]
        value = getattr(context, name, None)
        if value is not None:
            return value
    return default


def _require_operator_id(context: Any) -> str:
    operator_id = _ctx_get(context, "operator_id")
    if not operator_id:
        principal = _ctx_get(context, "principal")
        operator_id = _ctx_get(principal, "operator_id") if principal else None
    if not operator_id:
        raise UnauthorizedError("no authenticated Kyber session")
    return str(operator_id)


def _client_ip(request: Request) -> Optional[str]:
    if request.client and request.client.host:
        return request.client.host
    return None


def _user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")


# ── Request bodies ────────────────────────────────────────────────────────────

class InvitationCreateRequest(BaseModel):
    email: str
    role_template_ids: list[str] = Field(default_factory=list)
    allowed_environments: list[str] = Field(default_factory=list)
    ttl_hours: int = 24


class InvitationAcceptRequest(BaseModel):
    token: str
    state: Optional[str] = None
    code: Optional[str] = None


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RoleBindRequest(BaseModel):
    role_template_id: str
    environment: Optional[str] = None
    expires_at: Optional[str] = None


class BootstrapRequest(BaseModel):
    state: Optional[str] = None
    code: Optional[str] = None


# ── Authentication ────────────────────────────────────────────────────────────

@router.get("/auth/login", include_in_schema=True)
async def kyber_login(
    request: Request,
    next_path: Optional[str] = Query(default=None, alias="next"),
) -> RedirectResponse:
    """Begin a Google Workspace login.

    State, nonce and the PKCE verifier are generated and held server-side; the
    browser carries only the opaque ``state`` value back through Google.
    """
    client = get_oidc_client()
    redirect_uri = _callback_uri(request)
    transaction = oidc_transaction_store.start(
        redirect_uri=redirect_uri,
        next_path=next_path,
        client_ip=_client_ip(request),
    )
    try:
        url = client.build_authorization_url(
            state=transaction.state,
            nonce=transaction.nonce,
            code_challenge=transaction.code_challenge,
            redirect_uri=redirect_uri,
        )
    except OidcError as exc:
        raise BadRequestError(f"Kyber login is not configured: {exc.reason}") from exc

    await record_authentication_event(
        event_type="login_started",
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
        metadata={"provider": getattr(client, "provider_name", "google")},
    )
    metrics.increment("kyber_login_started_total")
    return RedirectResponse(url=url, status_code=307)


@router.get("/auth/callback")
async def kyber_callback(request: Request, code: str, state: str) -> dict:
    """Complete the login: exchange the code, resolve the principal, open a session."""
    client_ip = _client_ip(request)
    user_agent = _user_agent(request)

    transaction = oidc_transaction_store.consume(state)
    if transaction is None:
        await _deny_login("state_unknown", client_ip=client_ip, user_agent=user_agent)
        raise UnauthorizedError("invalid or expired login attempt")

    client = get_oidc_client()
    try:
        identity = await client.exchange_code(
            code=code,
            code_verifier=transaction.code_verifier,
            redirect_uri=transaction.redirect_uri,
            nonce=transaction.nonce,
        )
    except OidcError as exc:
        await _deny_login(exc.reason, client_ip=client_ip, user_agent=user_agent)
        raise UnauthorizedError("Google authentication failed") from exc

    principal = await principal_service.get_by_google_subject(identity.google_subject)
    if principal is None:
        # An uninvited Workspace account is denied here, not admitted with an
        # empty role set: Kyber is invite-only in the strong sense.
        await _deny_login(
            "principal_unknown",
            client_ip=client_ip,
            user_agent=user_agent,
            google_subject=identity.google_subject,
            email=identity.email,
        )
        raise ForbiddenError("this identity has no Kyber workforce principal")
    if not principal.is_active:
        await _deny_login(
            "principal_inactive",
            client_ip=client_ip,
            user_agent=user_agent,
            google_subject=identity.google_subject,
            email=identity.email,
            operator_id=principal.operator_id,
        )
        raise ForbiddenError("this workforce principal is not active")

    try:
        from services.kyber.sessions.service import session_service
    except ImportError as exc:  # pragma: no cover - only before sessions are mounted
        logger.error("kyber session service unavailable; refusing to fabricate a session")
        raise ForbiddenError(
            "Kyber session service is unavailable; no session was created"
        ) from exc

    session_result = await session_service.create_session(
        operator_id=principal.operator_id,
        google_subject=identity.google_subject,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    await principal_service.mark_login(principal.operator_id)
    await record_authentication_event(
        event_type="login_succeeded",
        operator_id=principal.operator_id,
        google_subject=identity.google_subject,
        email=identity.email,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    metrics.increment("kyber_auth_success_total")
    return APIResponse(
        data={
            "operator_id": principal.operator_id,
            "email": principal.email,
            "display_name": principal.display_name,
            "session": _serialize(session_result),
            "next": transaction.next_path,
        }
    ).to_dict()


@router.post("/auth/logout")
async def kyber_logout(
    request: Request,
    context: Any = Depends(_require(SELF_CAPABILITY)),
) -> dict:
    """End the current session. Idempotent from the caller's point of view."""
    operator_id = _require_operator_id(context)
    session_id = _ctx_get(context, "session_id")
    revoked = False
    try:
        from services.kyber.sessions.service import session_service
    except ImportError:  # pragma: no cover
        logger.error("kyber session service unavailable during logout")
    else:
        await session_service.revoke_session(session_id, reason="logout")
        revoked = True

    await record_authentication_event(
        event_type="logout",
        operator_id=operator_id,
        session_id=session_id,
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    metrics.increment("kyber_logout_total")
    return APIResponse(data={"logged_out": revoked, "session_id": session_id}).to_dict()


@router.get("/me")
async def kyber_me(context: Any = Depends(_require(SELF_CAPABILITY))) -> dict:
    """The caller's own authority, exactly as the backend computed it."""
    operator_id = _require_operator_id(context)
    principal = await principal_service.require_principal(operator_id)
    environment = str(_ctx_get(context, "environment", default="local"))

    template_ids = await principal_service.role_template_ids(
        operator_id, environment=environment
    )
    capabilities = await principal_service.effective_capabilities(
        operator_id, environment=environment
    )

    view = KyberPrincipalView(
        operator_id=principal.operator_id,
        email=principal.email,
        display_name=principal.display_name,
        employment_status=principal.employment_status,
        environment=environment,
        session_id=str(_ctx_get(context, "session_id", default="")),
        session_status=_ctx_get(context, "session_status", default="restricted"),
        authentication_strength=_ctx_get(
            context, "authentication_strength", default="none"
        ),
        device_id=_ctx_get(context, "device_id"),
        device_approval_state=_ctx_get(context, "device_approval_state"),
        role_template_ids=template_ids,
        capabilities=sorted(capabilities),
        max_disclosure=int(max_disclosure_for(template_ids)),
        max_action_class=max_action_class_for(template_ids),
        presence_expires_at=_ctx_get(context, "presence_expires_at"),
        authority_expires_at=_ctx_get(context, "authority_expires_at"),
        idle_expires_at=_ctx_get(context, "idle_expires_at"),
        step_up_expires_at=_ctx_get(context, "step_up_expires_at"),
        active_scope=_ctx_get(context, "active_scope"),
        may_approve_devices=bool(set(template_ids) & DEVICE_APPROVER_TEMPLATE_IDS),
    )
    return APIResponse(data=view.model_dump()).to_dict()


# ── Invitations ───────────────────────────────────────────────────────────────

@router.post("/workforce/invitations")
async def create_invitation(
    body: InvitationCreateRequest,
    context: Any = Depends(
        _require(
            WORKFORCE_MANAGE,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=4,
        )
    ),
) -> dict:
    """Issue an invitation. The raw token is in this response and nowhere else."""
    actor_id = _require_operator_id(context)
    invitation, token = await invitation_service.create_invitation(
        email=body.email,
        role_template_ids=body.role_template_ids,
        allowed_environments=body.allowed_environments,
        invited_by=actor_id,
        ttl_hours=body.ttl_hours,
    )
    return APIResponse(
        data={
            "invitation": invitation.model_dump(exclude={"token_hash"}),
            "token": token,
            "token_notice": "This token is shown once and is not recoverable.",
        }
    ).to_dict()


@router.get("/workforce/invitations")
async def list_invitations(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: Any = Depends(
        _require(WORKFORCE_MANAGE, disclosure=DisclosureLevel.D1_FLEET_AGGREGATE)
    ),
) -> dict:
    _require_operator_id(context)
    invitations = await invitation_service.list_invitations(status=status, limit=limit)
    return APIResponse(
        data={"invitations": [i.model_dump(exclude={"token_hash"}) for i in invitations]}
    ).to_dict()


@router.post("/workforce/invitations/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: str,
    context: Any = Depends(
        _require(
            WORKFORCE_MANAGE,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=4,
        )
    ),
) -> dict:
    actor_id = _require_operator_id(context)
    invitation = await invitation_service.revoke_invitation(
        invitation_id, actor_id=actor_id
    )
    return APIResponse(
        data={"invitation": invitation.model_dump(exclude={"token_hash"})}
    ).to_dict()


@router.post("/workforce/invitations/accept")
async def accept_invitation(request: Request, body: InvitationAcceptRequest) -> dict:
    """Redeem an invitation with a freshly verified Google identity.

    Unauthenticated by design — the invitation token plus a verified Google
    identity *is* the authentication. The identity comes from a completed OIDC
    transaction, never from the request body.
    """
    client_ip = _client_ip(request)
    user_agent = _user_agent(request)

    if not body.state or not body.code:
        raise BadRequestError(
            "accepting an invitation requires a completed Google login "
            "(state and code)"
        )
    transaction = oidc_transaction_store.consume(body.state)
    if transaction is None:
        await _deny_login("state_unknown", client_ip=client_ip, user_agent=user_agent)
        raise UnauthorizedError("invalid or expired login attempt")

    client = get_oidc_client()
    try:
        identity = await client.exchange_code(
            code=body.code,
            code_verifier=transaction.code_verifier,
            redirect_uri=transaction.redirect_uri,
            nonce=transaction.nonce,
        )
    except OidcError as exc:
        await _deny_login(exc.reason, client_ip=client_ip, user_agent=user_agent)
        raise UnauthorizedError("Google authentication failed") from exc

    principal = await invitation_service.accept_invitation(
        token=body.token,
        google_subject=identity.google_subject,
        email=identity.email,
        display_name=identity.display_name,
    )
    return APIResponse(
        data={
            "operator_id": principal.operator_id,
            "email": principal.email,
            "employment_status": principal.employment_status,
        }
    ).to_dict()


# ── Principals ────────────────────────────────────────────────────────────────

@router.get("/workforce/principals")
async def list_principals(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: Any = Depends(
        _require(WORKFORCE_MANAGE, disclosure=DisclosureLevel.D1_FLEET_AGGREGATE)
    ),
) -> dict:
    _require_operator_id(context)
    principals = await principal_service.list_principals(status=status, limit=limit)
    return APIResponse(
        data={"principals": [p.model_dump() for p in principals]}
    ).to_dict()


@router.get("/workforce/principals/{operator_id}")
async def get_principal(
    operator_id: str,
    context: Any = Depends(
        _require(WORKFORCE_MANAGE, disclosure=DisclosureLevel.D1_FLEET_AGGREGATE)
    ),
) -> dict:
    _require_operator_id(context)
    principal = await principal_service.require_principal(operator_id)
    bindings = await principal_service.list_role_bindings(
        operator_id, include_inactive=True
    )
    capabilities = await principal_service.effective_capabilities(operator_id)
    return APIResponse(
        data={
            "principal": principal.model_dump(),
            "role_bindings": [b.model_dump() for b in bindings],
            "capabilities": sorted(capabilities),
        }
    ).to_dict()


@router.post("/workforce/principals/{operator_id}/suspend")
async def suspend_principal(
    operator_id: str,
    body: ReasonRequest,
    context: Any = Depends(
        _require(
            WORKFORCE_MANAGE,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=4,
        )
    ),
) -> dict:
    """Immediate, authoritative removal of Kyber access. Reversible."""
    actor_id = _require_operator_id(context)
    principal = await principal_service.suspend(
        operator_id, actor_id=actor_id, reason=body.reason
    )
    return APIResponse(data={"principal": principal.model_dump()}).to_dict()


@router.post("/workforce/principals/{operator_id}/offboard")
async def offboard_principal_route(
    operator_id: str,
    body: ReasonRequest,
    context: Any = Depends(
        _require(
            WORKFORCE_MANAGE,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=5,
        )
    ),
) -> dict:
    """Terminal offboarding: identity, sessions, devices and scopes."""
    actor_id = _require_operator_id(context)
    report = await offboard_principal(
        operator_id, actor_id=actor_id, reason=body.reason
    )
    return APIResponse(data=report).to_dict()


# ── Role bindings ─────────────────────────────────────────────────────────────

@router.post("/workforce/principals/{operator_id}/roles")
async def bind_role(
    operator_id: str,
    body: RoleBindRequest,
    context: Any = Depends(
        _require(
            ROLE_MANAGE,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=5,
        )
    ),
) -> dict:
    actor_id = _require_operator_id(context)
    binding = await principal_service.bind_role(
        operator_id=operator_id,
        role_template_id=body.role_template_id,
        granted_by=actor_id,
        environment=body.environment,
        expires_at=body.expires_at,
    )
    return APIResponse(data={"role_binding": binding.model_dump()}).to_dict()


@router.delete("/workforce/roles/{binding_id}")
async def revoke_role_binding(
    binding_id: str,
    reason: str = Query(default="revoked by operator", min_length=3, max_length=500),
    context: Any = Depends(
        _require(
            ROLE_MANAGE,
            disclosure=DisclosureLevel.D1_FLEET_AGGREGATE,
            action_class=5,
        )
    ),
) -> dict:
    actor_id = _require_operator_id(context)
    binding = await principal_service.revoke_role_binding(
        binding_id, actor_id=actor_id, reason=reason
    )
    return APIResponse(data={"role_binding": binding.model_dump()}).to_dict()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

@router.post("/auth/bootstrap")
async def bootstrap_founder(request: Request, body: BootstrapRequest) -> dict:
    """Create the first workforce principal, once, from a verified Google login.

    Unauthenticated by necessity — there is no principal to authenticate as
    yet. Every other condition (env gate, zero principals, configured founder
    identity, unconsumed marker) is checked in
    :class:`~services.kyber.identity.bootstrap.FounderBootstrapService`.
    """
    client_ip = _client_ip(request)
    user_agent = _user_agent(request)

    if not await founder_bootstrap_service.is_available():
        raise ForbiddenError("founder bootstrap is not available")
    if not body.state or not body.code:
        raise BadRequestError("bootstrap requires a completed Google login")

    transaction = oidc_transaction_store.consume(body.state)
    if transaction is None:
        await _deny_login("state_unknown", client_ip=client_ip, user_agent=user_agent)
        raise UnauthorizedError("invalid or expired login attempt")

    client = get_oidc_client()
    try:
        identity = await client.exchange_code(
            code=body.code,
            code_verifier=transaction.code_verifier,
            redirect_uri=transaction.redirect_uri,
            nonce=transaction.nonce,
        )
    except OidcError as exc:
        await _deny_login(exc.reason, client_ip=client_ip, user_agent=user_agent)
        raise UnauthorizedError("Google authentication failed") from exc

    principal = await founder_bootstrap_service.bootstrap(
        google_subject=identity.google_subject,
        email=normalize_email(identity.email),
        display_name=identity.display_name,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    return APIResponse(
        data={
            "operator_id": principal.operator_id,
            "email": principal.email,
            "employment_status": principal.employment_status,
            "notice": "Disable KYBER_BOOTSTRAP_ENABLED now.",
        }
    ).to_dict()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _callback_uri(request: Request) -> str:
    """The redirect URI Google will send the browser back to."""
    from .oidc import OidcConfig

    configured = OidcConfig.from_env().redirect_uri
    if configured:
        return configured
    return str(request.url_for("kyber_callback"))


def _serialize(value: Any) -> Any:
    """Render a session-like object for the response without leaking a token.

    Session services return either the record or ``(record, raw_token)``. The
    raw token belongs in a cookie set by the session layer, never in a JSON
    body, so every key naming a token — raw or hashed — is dropped here.
    """
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        return _serialize(value[0]) if value else None
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if "token" not in k}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return {k: v for k, v in dump().items() if "token" not in k}
    return str(value)


async def _deny_login(
    reason: str,
    *,
    client_ip: Optional[str],
    user_agent: Optional[str],
    google_subject: Optional[str] = None,
    email: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> None:
    metrics.increment("kyber_auth_failure_total", labels={"reason": reason})
    await record_authentication_event(
        event_type="login_failed",
        outcome="failed",
        reason=reason,
        operator_id=operator_id,
        google_subject=google_subject,
        email=email,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    logger.warning(f"kyber login denied reason={reason}")
