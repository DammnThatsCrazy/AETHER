"""Authenticated organization profile and membership management routes."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from repositories.repos import asyncpg
from shared.common.common import (
    APIResponse,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PaginatedResponse,
    PaginationMeta,
    UnauthorizedError,
)
from shared.temporal import SYSTEM_CLOCK, parse_instant_strict, to_iso_utc

from .models import (
    InvitationCreateRequest,
    InvitationCreatedResponse,
    InvitationResponse,
    MemberRoleUpdate,
    OrganizationMemberResponse,
    OrganizationProfileResponse,
    OrganizationProfileUpdate,
    OrganizationRole,
)
from .repository import OrganizationRepository


router = APIRouter(prefix="/v1/account/organization", tags=["Account Organization"])
_repository = OrganizationRepository()

_READ_ROLES = frozenset(OrganizationRole)
_MANAGE_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})


def get_organization_repository() -> OrganizationRepository:
    """Dependency seam for tests and for future application wiring."""
    return _repository


def _tenant(request: Request):
    tenant = getattr(getattr(request, "state", None), "tenant", None)
    tenant_id = getattr(tenant, "tenant_id", None)
    if tenant is None or not tenant_id:
        raise UnauthorizedError("Authenticated tenant context is required")
    if getattr(tenant, "tenant_status", "active") not in {"active", "active_limited"}:
        raise ForbiddenError("Tenant account is not active")
    return tenant


def _state_role(tenant: Any) -> OrganizationRole | None:
    raw = (
        getattr(tenant, "organization_role", None)
        or getattr(tenant, "membership_role", None)
        or getattr(tenant, "role", None)
    )
    raw = getattr(raw, "value", raw)
    try:
        return OrganizationRole(str(raw))
    except (TypeError, ValueError):
        return None


async def _organization_or_404(tenant_id: str, repo: OrganizationRepository) -> dict[str, Any]:
    profile = await repo.get_profile(tenant_id)
    if profile is None:
        raise NotFoundError("Organization")
    return profile


async def _actor_role(
    tenant: Any, profile: dict[str, Any], repo: OrganizationRepository
) -> OrganizationRole:
    organization_id = getattr(tenant, "organization_id", None)
    if organization_id and organization_id != profile.get("organization_id"):
        raise ForbiddenError("Organization does not belong to the authenticated tenant context")

    user_id = getattr(tenant, "user_id", None)
    if user_id and user_id == profile.get("owner_user_id"):
        return OrganizationRole.OWNER

    member = await repo.get_active_member_by_user(profile["tenant_id"], user_id)
    if member is not None:
        try:
            return OrganizationRole(member["role"])
        except (KeyError, ValueError):
            raise ForbiddenError("Organization membership has an invalid role")

    # Legacy tenant credentials do not carry a principal membership row. Their
    # durable request context still carries the tenant role, so preserve read
    # access and tenant-admin behavior without trusting request input.
    role = _state_role(tenant)
    if role is not None and (not user_id or role in {OrganizationRole.ADMIN, OrganizationRole.VIEWER}):
        return role
    raise ForbiddenError("Authenticated principal is not an active organization member")


async def _authorize(
    request: Request,
    repo: OrganizationRepository,
    allowed: frozenset[OrganizationRole],
) -> tuple[Any, dict[str, Any], OrganizationRole]:
    tenant = _tenant(request)
    profile = await _organization_or_404(tenant.tenant_id, repo)
    role = await _actor_role(tenant, profile, repo)
    if role not in allowed:
        raise ForbiddenError(f"Organization role '{role.value}' cannot perform this action")
    return tenant, profile, role


def _profile_response(record: dict[str, Any]) -> dict[str, Any]:
    payload = {**record}
    payload.setdefault("organization_id", payload.get("id"))
    payload.pop("id", None)
    return OrganizationProfileResponse.model_validate(payload).model_dump(mode="json")


def _member_response(record: dict[str, Any]) -> dict[str, Any]:
    payload = {**record}
    payload.setdefault("member_id", payload.get("id"))
    payload.pop("id", None)
    return OrganizationMemberResponse.model_validate(payload).model_dump(mode="json")


def _invitation_response(record: dict[str, Any]) -> dict[str, Any]:
    payload = {**record}
    payload.setdefault("invitation_id", payload.get("id"))
    payload.pop("id", None)
    payload.pop("token_hash", None)
    payload.pop("expired_at", None)
    return InvitationResponse.model_validate(payload).model_dump(mode="json")


def _is_expired(record: dict[str, Any], now: datetime | None = None) -> bool:
    current = to_iso_utc(now or SYSTEM_CLOCK.now())
    try:
        expires_at = parse_instant_strict(str(record["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return True
    return expires_at <= parse_instant_strict(current)


async def _expire_pending(record: dict[str, Any], tenant_id: str, repo: OrganizationRepository) -> dict[str, Any]:
    if record.get("status") == "pending" and _is_expired(record):
        return await repo.update_invitation(
            tenant_id,
            record["id"],
            {"status": "expired", "expired_at": to_iso_utc(SYSTEM_CLOCK.now())},
        )
    return record


def _unique_violation(exc: Exception) -> bool:
    violation = getattr(asyncpg, "UniqueViolationError", None)
    return violation is not None and isinstance(exc, violation)


@router.get("")
@router.get("/profile")
async def get_organization_profile(request: Request) -> dict:
    _, profile, _ = await _authorize(request, get_organization_repository(), _READ_ROLES)
    return APIResponse(data=_profile_response(profile)).to_dict()


@router.patch("")
@router.patch("/profile")
async def update_organization_profile(
    request: Request,
    body: OrganizationProfileUpdate,
) -> dict:
    tenant, _, _ = await _authorize(request, get_organization_repository(), _MANAGE_ROLES)
    repo = get_organization_repository()
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ConflictError("At least one organization profile field is required")
    updated = await repo.update_profile(tenant.tenant_id, changes)
    return APIResponse(data=_profile_response(updated)).to_dict()


@router.get("/members")
async def list_organization_members(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    tenant, _, _ = await _authorize(request, get_organization_repository(), _READ_ROLES)
    repo = get_organization_repository()
    rows = await repo.list_members(tenant.tenant_id, limit=limit, offset=offset)
    total = await repo.count_members(tenant.tenant_id)
    return PaginatedResponse(
        data=[_member_response(row) for row in rows],
        pagination=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(rows) < total,
        ),
    ).to_dict()


@router.post("/invitations")
async def create_organization_invitation(
    request: Request,
    body: InvitationCreateRequest,
) -> dict:
    tenant, _, actor_role = await _authorize(request, get_organization_repository(), _MANAGE_ROLES)
    if body.role == OrganizationRole.OWNER:
        raise ForbiddenError("Ownership transfer requires an active member and the role-change endpoint")
    repo = get_organization_repository()
    existing = await repo.find_pending_invitation(tenant.tenant_id, body.email)
    if existing is not None:
        existing = await _expire_pending(existing, tenant.tenant_id, repo)
        if existing.get("status") == "pending":
            raise ConflictError("An active invitation already exists for this email")

    raw_token = secrets.token_urlsafe(32)
    now = SYSTEM_CLOCK.now()
    record = {
        "tenant_id": tenant.tenant_id,
        "email": body.email,
        "role": body.role.value,
        "status": "pending",
        "invited_by": getattr(tenant, "user_id", None) or tenant.tenant_id,
        "expires_at": (now + timedelta(hours=body.expires_in_hours)).isoformat(),
        "token_hash": hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
    }
    try:
        stored = await repo.create_invitation(tenant.tenant_id, record)
    except Exception as exc:
        if _unique_violation(exc):
            raise ConflictError("An active invitation already exists for this email") from exc
        raise
    response = InvitationCreatedResponse(
        **_invitation_response(stored),
        token=raw_token,
    )
    return APIResponse(
        data=response.model_dump(mode="json"),
        meta={"role": actor_role.value, "token_expires_at": stored["expires_at"]},
    ).to_dict()


@router.get("/invitations")
async def list_organization_invitations(request: Request) -> dict:
    tenant, _, _ = await _authorize(request, get_organization_repository(), _MANAGE_ROLES)
    repo = get_organization_repository()
    rows = await repo.list_invitations(tenant.tenant_id)
    safe_rows = []
    for row in rows:
        row = await _expire_pending(row, tenant.tenant_id, repo)
        safe_rows.append(_invitation_response(row))
    return APIResponse(data=safe_rows, meta={"count": len(safe_rows)}).to_dict()


@router.post("/invitations/{invitation_id}/revoke")
async def revoke_organization_invitation(request: Request, invitation_id: str) -> dict:
    tenant, _, _ = await _authorize(request, get_organization_repository(), _MANAGE_ROLES)
    repo = get_organization_repository()
    invitation = await repo.get_invitation(tenant.tenant_id, invitation_id)
    if invitation is None:
        raise NotFoundError("Invitation")
    invitation = await _expire_pending(invitation, tenant.tenant_id, repo)
    if invitation.get("status") != "pending":
        raise ConflictError("Only a pending invitation can be revoked")
    updated = await repo.update_invitation(
        tenant.tenant_id,
        invitation_id,
        {
            "status": "revoked",
            "revoked_at": to_iso_utc(SYSTEM_CLOCK.now()),
            "token_hash": None,
        },
    )
    return APIResponse(data=_invitation_response(updated)).to_dict()


@router.patch("/members/{member_id}/role")
async def change_organization_member_role(
    request: Request,
    member_id: str,
    body: MemberRoleUpdate,
) -> dict:
    tenant, profile, actor_role = await _authorize(request, get_organization_repository(), _MANAGE_ROLES)
    repo = get_organization_repository()
    member = await repo.get_member(tenant.tenant_id, member_id)
    if member is None or member.get("status") != "active":
        raise NotFoundError("Organization member")
    target_role = body.role
    if target_role == OrganizationRole.OWNER:
        if actor_role != OrganizationRole.OWNER:
            raise ForbiddenError("Only the current owner can transfer organization ownership")
        if member.get("user_id") == profile.get("owner_user_id"):
            return APIResponse(data=_member_response(member)).to_dict()
        current_owner_id = profile.get("owner_user_id")
        current_owner = await repo.get_active_member_by_user(tenant.tenant_id, current_owner_id)
        updated_target = await repo.update_member(tenant.tenant_id, member_id, {"role": "owner"})
        if current_owner is not None:
            await repo.update_member(tenant.tenant_id, current_owner["id"], {"role": "admin"})
        await repo.update_profile(tenant.tenant_id, {"owner_user_id": member["user_id"]})
        return APIResponse(data=_member_response(updated_target)).to_dict()

    if member.get("user_id") == profile.get("owner_user_id"):
        raise ConflictError("The current owner must transfer ownership before changing this role")
    if body.role not in {OrganizationRole.ADMIN, OrganizationRole.MEMBER, OrganizationRole.VIEWER}:
        raise ForbiddenError("Invalid organization member role")
    updated = await repo.update_member(tenant.tenant_id, member_id, {"role": target_role.value})
    return APIResponse(data=_member_response(updated)).to_dict()


@router.delete("/members/{member_id}")
async def remove_organization_member(request: Request, member_id: str) -> dict:
    tenant, profile, _ = await _authorize(request, get_organization_repository(), _MANAGE_ROLES)
    repo = get_organization_repository()
    member = await repo.get_member(tenant.tenant_id, member_id)
    if member is None or member.get("status") != "active":
        raise NotFoundError("Organization member")
    if member.get("user_id") == profile.get("owner_user_id"):
        raise ConflictError("The organization owner cannot be removed")
    if member.get("user_id") == getattr(tenant, "user_id", None):
        raise ConflictError("An administrator cannot remove their own membership")
    removed = await repo.remove_member(tenant.tenant_id, member_id)
    return APIResponse(data={"member_id": removed["member_id"], "removed": True}).to_dict()


__all__ = ["get_organization_repository", "router"]
