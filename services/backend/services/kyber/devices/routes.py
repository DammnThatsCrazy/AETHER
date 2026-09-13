"""HTTP surface for Kyber device trust.

Every route here is guarded by the Kyber access dependency. The import is lazy
because the access package is built alongside this one; if it cannot be
imported the fallback dependency **denies**. There is no configuration, import
failure or deployment slice in which these routes answer without an
authorization decision having been made.

The router is intentionally *not* mounted here — the application assembles it,
so that mounting is a deliberate act with the rest of the Kyber plane.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from shared.common.common import (
    APIResponse,
    BadRequestError,
    ForbiddenError,
    UnauthorizedError,
)
from shared.logger.logger import get_logger

from ..access.capabilities import (
    ACTION_CLASS_ANNOTATE,
    ACTION_CLASS_HIGH_IMPACT,
    ACTION_CLASS_READ,
    SELF_CAPABILITY,
)
from ..access.contracts import TrustedDevice
from ..access.roles import DEVICE_APPROVER_TEMPLATE_IDS
from .approvals import (
    GRANT_COOKIE_NAME,
    MAX_REGISTRATION_DAYS,
    MIN_REGISTRATION_DAYS,
    device_approval_service,
)
from .device_proof import device_proof_service
from .risk import browser_family, device_risk_service
from .webauthn import webauthn_service

logger = get_logger("aether.kyber.devices.routes")

router = APIRouter(prefix="/v1/kyber/devices", tags=["Kyber Devices"])

#: Capability that gates every approver-only transition.
DEVICE_APPROVE_CAPABILITY = "kyber.device.approve"

#: Default grant lifetime when the caller does not supply one. The most
#: conservative ``device_registration_days`` across the role templates, so an
#: omitted value never buys a longer-lived grant than a deliberate one.
DEFAULT_REGISTRATION_DAYS = 30


def _require(capability: str, **kw: Any) -> Callable[..., Any]:
    """Build the Kyber access dependency for one capability.

    Falls back to a dependency that *denies* when the access package is not
    importable. A missing authorization module must never read as "no
    authorization required".
    """
    try:
        from services.kyber.access.dependencies import require_kyber_access
    except ImportError:  # pragma: no cover - only while the access plane is absent
        logger.error(
            "kyber access dependency unavailable; device routes will deny capability=%s",
            capability,
        )

        async def _deny() -> None:
            raise ForbiddenError("Kyber access control is unavailable")

        return _deny
    return require_kyber_access(capability, **kw)


# ── Request bodies ────────────────────────────────────────────────────────────

class RegistrationOptionsRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class RegistrationVerifyRequest(BaseModel):
    challenge_id: str
    credential: dict[str, Any]
    display_name: str = Field(min_length=1, max_length=80)
    platform_family: Optional[str] = None
    #: base64url SPKI ECDSA P-256 public key generated non-extractably in this
    #: browser profile. Optional only so the two halves of enrollment can be
    #: split across calls; a device without one can never become usable.
    proof_public_key: Optional[str] = None


class ProofChallengeRequest(BaseModel):
    device_id: str


class ProofVerifyRequest(BaseModel):
    device_id: str
    challenge_id: str
    signature: str


class ApproveRequest(BaseModel):
    registration_days: int = Field(
        default=DEFAULT_REGISTRATION_DAYS,
        ge=MIN_REGISTRATION_DAYS,
        le=MAX_REGISTRATION_DAYS,
    )


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RenameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


# ── Principal helpers ─────────────────────────────────────────────────────────

def _field(principal: Any, name: str) -> Any:
    """Read one attribute from whatever shape the access dependency yields."""
    if principal is None:
        return None
    if isinstance(principal, dict):
        return principal.get(name)
    return getattr(principal, name, None)


def _operator_id(principal: Any) -> str:
    """The authenticated operator, or a denial.

    Fails closed: a principal the device plane cannot read is not a principal
    it will act for.
    """
    operator_id = _field(principal, "operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        raise UnauthorizedError("no authenticated Kyber operator on this request")
    return operator_id


def _role_template_ids(principal: Any) -> list[str]:
    raw = _field(principal, "role_template_ids") or []
    return [t for t in raw if isinstance(t, str)]


def _is_approver(principal: Any) -> bool:
    return bool(set(_role_template_ids(principal)) & DEVICE_APPROVER_TEMPLATE_IDS)


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _device_view(device: TrustedDevice) -> dict[str, Any]:
    """Public projection of a device. Never includes the grant hash."""
    return {
        "device_id": device.device_id,
        "operator_id": device.operator_id,
        "display_name": device.display_name,
        "platform_family": device.platform_family,
        "browser_family": device.browser_family,
        "approval_state": device.approval_state,
        "risk_state": device.risk_state,
        "requested_at": device.requested_at,
        "approved_at": device.approved_at,
        "approved_by": device.approved_by,
        "expires_at": device.expires_at,
        "last_used_at": device.last_used_at,
        "revoked_at": device.revoked_at,
        "revocation_reason": device.revocation_reason,
        "risk_signals": (device.metadata or {}).get("risk_signals", []),
    }


# ── WebAuthn enrollment ───────────────────────────────────────────────────────

@router.post("/registration/options")
async def registration_options(
    body: RegistrationOptionsRequest,
    principal: Any = Depends(_require(SELF_CAPABILITY, action_class=ACTION_CLASS_READ)),
) -> dict[str, Any]:
    """Start a WebAuthn registration ceremony for the calling operator."""
    operator_id = _operator_id(principal)
    existing = [
        c.credential_id for c in await webauthn_service.list_credentials(operator_id)
    ]
    result = await webauthn_service.registration_options(
        operator_id=operator_id,
        display_name=body.display_name,
        existing_credential_ids=existing,
    )
    return APIResponse(data=result).to_dict()


@router.post("/registration/verify")
async def registration_verify(
    body: RegistrationVerifyRequest,
    request: Request,
    principal: Any = Depends(
        _require(SELF_CAPABILITY, action_class=ACTION_CLASS_ANNOTATE)
    ),
) -> dict[str, Any]:
    """Finish enrollment: verify the credential, create the pending device.

    The device is **pending** when this returns. It grants nothing until a
    separate approver acts on it, which is what keeps a passkey that syncs onto
    a second machine from silently extending trust to that machine.
    """
    operator_id = _operator_id(principal)
    credential = await webauthn_service.verify_registration(
        operator_id=operator_id,
        credential=body.credential,
        expected_challenge_id=body.challenge_id,
        display_name=body.display_name,
        platform_family=body.platform_family,
        browser_family=browser_family(request.headers.get("user-agent")),
    )

    proof_key_id: Optional[str] = None
    if body.proof_public_key:
        proof_key = await device_proof_service.register_proof_key(
            device_id=credential.device_id,
            operator_id=operator_id,
            public_key_b64=body.proof_public_key,
        )
        proof_key_id = proof_key.proof_key_id

    device = await device_approval_service.get_device(credential.device_id)
    return APIResponse(
        data={
            "device": _device_view(device) if device else None,
            "credential_pk": credential.credential_pk,
            "proof_key_id": proof_key_id,
            "approval_required": True,
        }
    ).to_dict()


# ── Device proof ──────────────────────────────────────────────────────────────

@router.post("/proof/challenge")
async def proof_challenge(
    body: ProofChallengeRequest,
    principal: Any = Depends(_require(SELF_CAPABILITY, action_class=ACTION_CLASS_READ)),
) -> dict[str, Any]:
    """Issue a single-use device-proof challenge for one of the caller's devices."""
    operator_id = _operator_id(principal)
    device = await device_approval_service.get_device(body.device_id)
    if device is None or device.operator_id != operator_id:
        # Same answer either way: never confirm another operator's device id.
        raise UnauthorizedError("device is not available to this operator")

    challenge_id, challenge = await device_proof_service.issue_challenge(
        device_id=body.device_id
    )
    return APIResponse(
        data={"challenge_id": challenge_id, "challenge": challenge}
    ).to_dict()


@router.post("/proof/verify")
async def proof_verify(
    body: ProofVerifyRequest,
    request: Request,
    principal: Any = Depends(_require(SELF_CAPABILITY, action_class=ACTION_CLASS_READ)),
) -> dict[str, Any]:
    """Verify a device-proof signature and report whether the device is usable."""
    operator_id = _operator_id(principal)
    device = await device_approval_service.get_device(body.device_id)
    if device is None or device.operator_id != operator_id:
        raise UnauthorizedError("device is not available to this operator")

    verified = await device_proof_service.verify_proof(
        device_id=body.device_id,
        challenge_id=body.challenge_id,
        signature_b64=body.signature,
    )
    usable, reason = await device_approval_service.is_usable(body.device_id)
    if verified:
        await device_approval_service.touch(body.device_id)
        refreshed = await device_approval_service.get_device(body.device_id)
        if refreshed is not None:
            await device_risk_service.evaluate(
                refreshed,
                client_ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )

    return APIResponse(
        data={
            "verified": verified,
            "device_usable": bool(verified and usable),
            "reason": None if (verified and usable) else (reason or "device_proof_invalid"),
        }
    ).to_dict()


# ── Listing ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_devices(
    operator_id: Optional[str] = Query(default=None),
    principal: Any = Depends(_require(SELF_CAPABILITY, action_class=ACTION_CLASS_READ)),
) -> dict[str, Any]:
    """List the caller's devices; approvers may list any operator's."""
    caller = _operator_id(principal)
    target = operator_id or caller
    if target != caller and not _is_approver(principal):
        raise ForbiddenError("listing another operator's devices requires an approver role")

    devices = await device_approval_service.list_devices(target)
    return APIResponse(
        data={
            "operator_id": target,
            "devices": [_device_view(d) for d in devices],
        }
    ).to_dict()


# ── Approver transitions ──────────────────────────────────────────────────────

@router.post("/{device_id}/approve")
async def approve_device(
    device_id: str,
    body: ApproveRequest,
    response: Response,
    principal: Any = Depends(
        _require(DEVICE_APPROVE_CAPABILITY, action_class=ACTION_CLASS_HIGH_IMPACT)
    ),
) -> dict[str, Any]:
    """Approve a pending device and set its grant cookie.

    This endpoint is called *from the device being approved*: an approver
    authenticates on the operator's machine and approves it there. That is why
    the grant lands as a ``__Host-`` cookie on this response rather than being
    returned as a token for someone to forward — the raw grant exists for the
    duration of this response and is never persisted or repeatable.
    """
    caller = _operator_id(principal)
    device, grant_token = await device_approval_service.approve_device(
        device_id,
        actor_id=caller,
        actor_role_template_ids=_role_template_ids(principal),
        registration_days=body.registration_days,
    )
    response.set_cookie(
        GRANT_COOKIE_NAME,
        grant_token,
        max_age=body.registration_days * 24 * 60 * 60,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return APIResponse(
        data={"device": _device_view(device), "grant_delivery": "cookie"}
    ).to_dict()


@router.post("/{device_id}/suspend")
async def suspend_device(
    device_id: str,
    body: ReasonRequest,
    principal: Any = Depends(
        _require(DEVICE_APPROVE_CAPABILITY, action_class=ACTION_CLASS_HIGH_IMPACT)
    ),
) -> dict[str, Any]:
    """Pause a device without destroying its enrollment."""
    caller = _operator_id(principal)
    device = await device_approval_service.suspend_device(
        device_id, actor_id=caller, reason=body.reason
    )
    return APIResponse(data={"device": _device_view(device)}).to_dict()


@router.post("/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    body: ReasonRequest,
    response: Response,
    principal: Any = Depends(
        _require(DEVICE_APPROVE_CAPABILITY, action_class=ACTION_CLASS_HIGH_IMPACT)
    ),
) -> dict[str, Any]:
    """Revoke a device and every session bound to it."""
    caller = _operator_id(principal)
    device = await device_approval_service.revoke_device(
        device_id, actor_id=caller, reason=body.reason
    )
    await device_proof_service.revoke_proof_key(
        device_id, actor_id=caller, reason=body.reason
    )
    response.delete_cookie(GRANT_COOKIE_NAME, path="/")
    return APIResponse(
        data={
            "device": _device_view(device),
            "session_revocation": (device.metadata or {}).get("session_revocation"),
        }
    ).to_dict()


@router.post("/{device_id}/rename")
async def rename_device(
    device_id: str,
    body: RenameRequest,
    principal: Any = Depends(
        _require(SELF_CAPABILITY, action_class=ACTION_CLASS_ANNOTATE)
    ),
) -> dict[str, Any]:
    """Rename one of the caller's own devices. Approvers may rename any."""
    caller = _operator_id(principal)
    existing = await device_approval_service.get_device(device_id)
    if existing is None:
        raise UnauthorizedError("device is not available to this operator")
    if existing.operator_id != caller and not _is_approver(principal):
        raise UnauthorizedError("device is not available to this operator")
    if not body.display_name.strip():
        raise BadRequestError("display_name is required")

    device = await device_approval_service.rename_device(
        device_id, actor_id=caller, display_name=body.display_name
    )
    return APIResponse(data={"device": _device_view(device)}).to_dict()


__all__ = ["DEFAULT_REGISTRATION_DAYS", "DEVICE_APPROVE_CAPABILITY", "router"]
