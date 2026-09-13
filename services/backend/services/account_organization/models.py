"""Contracts for the account organization management surface.

These DTOs intentionally contain no invitation secret or token digest. The
one-time token is represented only by :class:`InvitationCreatedResponse`,
which is returned by the create operation and never by a later read.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _clean_required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


class OrganizationProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str
    tenant_id: str
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    owner_user_id: Optional[str] = None
    status: str = "active"
    created_at: str
    updated_at: str


class OrganizationProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=63)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", "description")
    @classmethod
    def normalize_text(cls, value: Optional[str], info):
        if value is None:
            return value
        return _clean_required_text(value, info.field_name)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip().lower()
        if not _SLUG_RE.fullmatch(value):
            raise ValueError("slug must contain lowercase letters, numbers, and internal hyphens")
        return value


class OrganizationMemberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: str
    tenant_id: str
    user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: OrganizationRole
    status: str = "active"
    created_at: str
    updated_at: str


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: OrganizationRole


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    role: OrganizationRole = OrganizationRole.MEMBER
    expires_in_hours: int = Field(default=168, ge=1, le=720)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("email must be a valid email address")
        return value


class InvitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_id: str
    tenant_id: str
    email: str
    role: OrganizationRole
    status: str
    invited_by: str
    expires_at: str
    revoked_at: Optional[str] = None
    created_at: str
    updated_at: str


class InvitationCreatedResponse(InvitationResponse):
    """Creation response. ``token`` is deliberately absent from list DTOs."""

    token: str

