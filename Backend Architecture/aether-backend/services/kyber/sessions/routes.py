"""Kyber session and step-up endpoints.

What is deliberately absent matters as much as what is here: there is no route
that mints a session, extends one, or hands back a raw handle. Sign-in lives in
the identity plane, where the Google assertion and the device proof are
verified; these routes only inspect and end what that flow produced, plus raise
and verify a step-up elevation.

The router is intentionally **not** mounted in ``main.py``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError

from ..access.capabilities import SELF_CAPABILITY
from ..access.dependencies import (
    KyberAccessContext,
    require_kyber_access,
    require_kyber_presence,
)
from .cookies import set_csrf_cookie, set_session_cookie
from .service import session_service
from .step_up import step_up_service

router = APIRouter(prefix="/v1/kyber/auth", tags=["Kyber Sessions"])

#: Ending someone else's session is workforce administration, not self-service.
_MANAGE_CAPABILITY = "kyber.workforce.manage"


class StepUpOptionsRequest(BaseModel):
    """Body for requesting a step-up challenge."""

    capability_id: Optional[str] = None


class StepUpVerifyRequest(BaseModel):
    """Body for completing a step-up with a signed assertion."""

    challenge_id: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    capability_id: Optional[str] = None
    reason: Optional[str] = None
    ttl_minutes: Optional[int] = None


def _session_body(session, *, include_step_up: Optional[dict] = None) -> dict:
    """Body-safe session representation. Never carries a token or a digest."""
    body = {
        "session_id": session.session_id,
        "operator_id": session.operator_id,
        "device_id": session.device_id,
        "status": session.status,
        "authentication_strength": session.authentication_strength,
        "authentication_methods": session.authentication_methods,
        "environment": session.environment,
        "presence_expires_at": session.presence_expires_at,
        "authority_expires_at": session.authority_expires_at,
        "idle_expires_at": session.idle_expires_at,
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "rotated_at": session.rotated_at,
        "revoked_at": session.revoked_at,
        "risk_state": session.risk_state,
    }
    if include_step_up is not None:
        body.update(include_step_up)
    return body


@router.get("/session")
async def read_session(
    request: Request,
    response: Response,
    context: KyberAccessContext = Depends(require_kyber_presence()),
) -> dict:
    """The caller's current session state, plus a fresh CSRF token.

    The CSRF token is returned in the body *and* set as an HttpOnly cookie. The
    application echoes the body value in ``X-Kyber-CSRF``; script cannot read
    the cookie copy, so a cross-site request cannot produce a matching pair.
    """
    session = context.session
    step_up = await step_up_service.describe(session.session_id)
    csrf = await session_service.issue_csrf_token(session.session_id)
    if csrf:
        set_csrf_cookie(response, csrf)
    return APIResponse(
        data=_session_body(session, include_step_up=step_up),
        meta={"csrf_token": csrf, "granted_disclosure": int(context.granted_disclosure)},
    ).to_dict()


@router.post("/step-up/options")
async def step_up_options(
    request: Request,
    body: StepUpOptionsRequest,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """Issue an authenticator challenge for the session's bound device."""
    device_id = context.session.device_id
    if not device_id:
        raise ForbiddenError("Step-up requires a device-bound session")
    challenge_id, challenge = await step_up_service.issue_challenge(device_id=device_id)
    return APIResponse(
        data={
            "challenge_id": challenge_id,
            "challenge": challenge,
            "device_id": device_id,
            "capability_id": body.capability_id,
        }
    ).to_dict()


@router.post("/step-up/verify")
async def step_up_verify(
    request: Request,
    response: Response,
    body: StepUpVerifyRequest,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """Verify an assertion and elevate the session.

    A successful elevation rotates the session handle, so the response sets a
    new session cookie. A handle captured before the elevation cannot ride it.
    """
    session = context.session
    grant, raw_token = await step_up_service.grant_and_rotate(
        session_id=session.session_id,
        operator_id=context.operator_id,
        device_id=session.device_id,
        capability_id=body.capability_id,
        reason=body.reason,
        ttl_minutes=body.ttl_minutes,
        challenge_id=body.challenge_id,
        signature_b64=body.signature,
    )
    rotated = await session_service.get(session.session_id)
    set_session_cookie(response, raw_token)
    csrf = await session_service.issue_csrf_token(session.session_id)
    if csrf:
        set_csrf_cookie(response, csrf)
    return APIResponse(
        data={
            "grant_id": grant.grant_id,
            "capability_id": grant.capability_id,
            "expires_at": grant.expires_at,
            "session": _session_body(rotated) if rotated else None,
        },
        meta={"csrf_token": csrf},
    ).to_dict()


@router.get("/sessions")
async def list_own_sessions(
    request: Request,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """Every session the caller holds. Self only — never another operator's."""
    sessions = await session_service.list_for_operator(context.operator_id)
    return APIResponse(
        data=[_session_body(s) for s in sessions],
        meta={"count": len(sessions), "current_session_id": context.session.session_id},
    ).to_dict()


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    request: Request,
    session_id: str,
    context: KyberAccessContext = Depends(require_kyber_access(SELF_CAPABILITY)),
) -> dict:
    """End a session.

    Callers may always end their own sessions. Ending someone else's requires
    ``kyber.workforce.manage`` — being able to see a session is not being able
    to end it.
    """
    target = await session_service.get(session_id)
    if target is None:
        raise NotFoundError("Kyber session")
    if target.operator_id != context.operator_id and not context.has_capability(_MANAGE_CAPABILITY):
        raise ForbiddenError("Ending another operator's session requires workforce administration")

    revoked = await session_service.revoke(
        session_id,
        reason="self_service" if target.operator_id == context.operator_id else "workforce_admin",
    )
    await step_up_service.revoke_for_session(session_id)
    return APIResponse(data=_session_body(revoked) if revoked else None).to_dict()


__all__ = ["StepUpOptionsRequest", "StepUpVerifyRequest", "router"]
