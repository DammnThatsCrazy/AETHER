"""Mobile installation + push-subscription Pydantic contracts — twin of
packages/shared/installation.ts.

Drift-guarded by tests/contracts/test_installation_contract_parity.py. Wire fields
are snake_case (decision-log D6). A push token is never carried in these records in
the clear: only its `token_hash` (for dedupe) is stored; the encrypted token lives
in the credential platform.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

INSTALLATION_PLATFORMS: tuple[str, ...] = ("ios", "android", "web")
INSTALLATION_APP_KINDS: tuple[str, ...] = ("aether", "kyber")
PUSH_PROVIDERS: tuple[str, ...] = ("apns", "fcm", "web_push")
INSTALLATION_TRUST_STATES: tuple[str, ...] = ("registered", "trusted", "revoked")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MobileInstallation(_Base):
    id: str
    principal_id: str
    tenant_id: Optional[str] = None
    app_kind: str
    platform: str
    bundle_id: str
    environment: str
    device_name: Optional[str] = None
    trust_state: str = "registered"
    app_version: Optional[str] = None
    distribution_profile: Optional[str] = None
    created_at: str
    last_seen_at: Optional[str] = None
    revoked_at: Optional[str] = None

    @field_validator("app_kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in INSTALLATION_APP_KINDS:
            raise ValueError(f"app_kind must be one of {INSTALLATION_APP_KINDS}")
        return v

    @field_validator("platform")
    @classmethod
    def _platform(cls, v: str) -> str:
        if v not in INSTALLATION_PLATFORMS:
            raise ValueError(f"platform must be one of {INSTALLATION_PLATFORMS}")
        return v

    @field_validator("trust_state")
    @classmethod
    def _trust(cls, v: str) -> str:
        if v not in INSTALLATION_TRUST_STATES:
            raise ValueError(f"trust_state must be one of {INSTALLATION_TRUST_STATES}")
        return v


class InstallationRegistration(_Base):
    """Client-supplied registration request. The server mints id/trust_state and
    stores the encrypted push token via the credential platform (not here)."""

    app_kind: str
    platform: str
    bundle_id: str
    environment: str
    device_name: Optional[str] = None
    push_token: Optional[str] = None
    push_provider: Optional[str] = None
    app_version: Optional[str] = None
    distribution_profile: Optional[str] = None


class PushSubscription(_Base):
    id: str
    installation_id: str
    principal_id: str
    platform: str
    provider: str
    token_hash: str
    environment: str
    active: bool = True
    created_at: str
    revoked_at: Optional[str] = None

    @field_validator("provider")
    @classmethod
    def _provider(cls, v: str) -> str:
        if v not in PUSH_PROVIDERS:
            raise ValueError(f"provider must be one of {PUSH_PROVIDERS}")
        return v


class InstallationRevocation(_Base):
    installation_id: str
    reason: Optional[str] = None
