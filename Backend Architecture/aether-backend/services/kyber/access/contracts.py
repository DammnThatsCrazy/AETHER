"""Typed records for the Kyber workforce identity, device trust and access plane.

One module owns every persisted shape so the identity, device, session and
access packages agree on field names without importing each other. Each model
here corresponds 1:1 to a table created by the
``kyber_workforce_identity`` migration.

Nothing in this module ever carries a secret. Invitation tokens, session
tokens and device grants are stored as sha256 digests only; WebAuthn private
keys, biometric templates, device PINs and Google credentials are never
received, let alone persisted.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from services.security.contracts import AccessRole
from shared.common.common import utc_now

from .disclosure import DisclosureLevel

# ── Vocabularies ──────────────────────────────────────────────────────────────

EmploymentStatus = Literal["invited", "active", "suspended", "offboarded"]

InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]

DeviceApprovalState = Literal["pending", "approved", "suspended", "revoked", "expired"]

DeviceRiskState = Literal["ok", "suspect", "blocked"]

#: A session is `restricted` until its device is approved, `risk_limited` when a
#: risk signal downgraded it, and `locked` when it needs re-authentication
#: before it can be used again.
SessionStatus = Literal[
    "restricted", "active", "risk_limited", "revoked", "expired", "locked"
]

#: Which authentication factors a session actually presented. Authority
#: sessions require at minimum google_oidc + webauthn + device_proof.
AuthenticationMethod = Literal[
    "google_oidc", "webauthn", "device_proof", "device_grant", "bootstrap"
]

#: Coarse strength band derived from the presented methods.
AuthenticationStrength = Literal["none", "identity_only", "device_bound", "stepped_up"]

AccessScopePurpose = Literal[
    "incident_response",
    "customer_support",
    "compliance_audit",
    "security_investigation",
    "data_request",
    "diagnostics",
    "break_glass",
    "product_validation",
]

AccessScopeStatus = Literal["active", "expired", "exited", "revoked"]

AuthenticationEventType = Literal[
    "login_started",
    "login_succeeded",
    "login_failed",
    "logout",
    "session_created",
    "session_rotated",
    "session_revoked",
    "step_up_granted",
    "step_up_failed",
    "device_registered",
    "device_approved",
    "device_revoked",
    "bootstrap_completed",
    "directory_reconciled",
]

#: Why a request was denied. Every value is safe to return to the caller — none
#: of them disclose whether a principal, device or tenant exists.
DenialReason = Literal[
    "no_session",
    "session_expired",
    "session_revoked",
    "session_restricted",
    "principal_inactive",
    "principal_unknown",
    "device_unapproved",
    "device_revoked",
    "device_mismatch",
    "device_proof_invalid",
    "capability_missing",
    "disclosure_exceeded",
    "action_class_exceeded",
    "scope_missing",
    "scope_expired",
    "scope_tenant_mismatch",
    "step_up_required",
    "approval_required",
    "environment_not_allowed",
    "directory_stale",
    "legacy_identity_disabled",
]


def now_iso() -> str:
    return utc_now().isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ── Workforce identity ────────────────────────────────────────────────────────

class WorkforcePrincipal(BaseModel):
    """An Olympus Labs employee. Never an Aether tenant.

    ``google_subject`` is the identity key — it is stable across email changes,
    which is why email is normalized for display and invitation matching but is
    never the primary key.
    """

    operator_id: str = Field(default_factory=lambda: _id("op"))
    google_subject: Optional[str] = None
    email: str
    display_name: Optional[str] = None
    employment_status: EmploymentStatus = "invited"
    department: Optional[str] = None
    #: False disables Kyber access without altering employment status.
    kyber_enabled: bool = True
    #: Empty means "every configured environment"; otherwise an explicit list.
    allowed_environments: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    created_by: Optional[str] = None
    activated_at: Optional[str] = None
    suspended_at: Optional[str] = None
    offboarded_at: Optional[str] = None
    last_directory_sync_at: Optional[str] = None
    last_login_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.employment_status == "active" and self.kyber_enabled


class WorkforceInvitation(BaseModel):
    """A single-use invitation. The raw token is returned once and never stored."""

    invitation_id: str = Field(default_factory=lambda: _id("inv"))
    token_hash: str
    email: str
    role_template_ids: list[str] = Field(default_factory=list)
    allowed_environments: list[str] = Field(default_factory=list)
    status: InvitationStatus = "pending"
    invited_by: str
    expires_at: str
    created_at: str = Field(default_factory=now_iso)
    accepted_at: Optional[str] = None
    accepted_by_operator_id: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleBinding(BaseModel):
    """Binds a workforce principal to a Kyber role template."""

    binding_id: str = Field(default_factory=lambda: _id("rb"))
    operator_id: str
    role_template_id: str
    access_roles: list[AccessRole] = Field(default_factory=list)
    environment: Optional[str] = None
    granted_by: str
    granted_at: str = Field(default_factory=now_iso)
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    reason: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class CapabilityGrant(BaseModel):
    """A capability granted to (or explicitly denied for) one principal.

    Grants layer on top of role templates for the cases a template does not
    cover. A ``denied`` grant always wins over any template that would allow it,
    so revoking one capability never requires rebuilding a role.
    """

    grant_id: str = Field(default_factory=lambda: _id("cg"))
    operator_id: str
    capability_id: str
    effect: Literal["allow", "deny"] = "allow"
    environment: Optional[str] = None
    granted_by: str
    granted_at: str = Field(default_factory=now_iso)
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    reason: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


# ── Device trust ──────────────────────────────────────────────────────────────

class TrustedDevice(BaseModel):
    """A personal device approved for Kyber access.

    Kyber never learns anything that would let it impersonate the device: no
    private key, no biometric template, no local PIN. What it holds is a public
    key, an approval record and a revocable grant.
    """

    device_id: str = Field(default_factory=lambda: _id("dev"))
    operator_id: str
    display_name: str
    platform_family: Optional[str] = None
    browser_family: Optional[str] = None
    approval_state: DeviceApprovalState = "pending"
    risk_state: DeviceRiskState = "ok"
    #: sha256 of the opaque device-grant cookie value. Absent until approval.
    grant_hash: Optional[str] = None
    requested_at: str = Field(default_factory=now_iso)
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    suspended_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revocation_reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.approval_state == "approved" and self.risk_state != "blocked"


class WebAuthnCredential(BaseModel):
    """A platform authenticator credential bound to one device record."""

    credential_pk: str = Field(default_factory=lambda: _id("wac"))
    device_id: str
    operator_id: str
    #: base64url credential id as issued by the authenticator. Unique.
    credential_id: str
    #: base64url-encoded COSE public key.
    public_key: str
    sign_count: int = 0
    credential_attachment: Optional[str] = None
    credential_transports: list[str] = Field(default_factory=list)
    aaguid: Optional[str] = None
    backup_eligible: bool = False
    backup_state: bool = False
    created_at: str = Field(default_factory=now_iso)
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class DeviceProofKey(BaseModel):
    """A browser-profile-bound ECDSA P-256 public key.

    This is what a synced passkey cannot carry. A WebAuthn credential may
    replicate to the operator's other personal machines through the platform's
    passkey sync; the proof key is generated non-extractably in one browser
    profile and stays there, so presenting the credential elsewhere still fails
    the device check.
    """

    proof_key_id: str = Field(default_factory=lambda: _id("dpk"))
    device_id: str
    operator_id: str
    #: base64url-encoded SPKI public key (ECDSA P-256).
    public_key: str
    algorithm: str = "ES256"
    created_at: str = Field(default_factory=now_iso)
    last_verified_at: Optional[str] = None
    revoked_at: Optional[str] = None


class DeviceApprovalEvent(BaseModel):
    """An immutable record of every device-state transition."""

    event_id: str = Field(default_factory=lambda: _id("dae"))
    device_id: str
    operator_id: str
    action: Literal["requested", "approved", "suspended", "revoked", "renamed", "reapproved"]
    actor_id: str
    from_state: Optional[DeviceApprovalState] = None
    to_state: Optional[DeviceApprovalState] = None
    reason: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Sessions ──────────────────────────────────────────────────────────────────

class WorkforceSession(BaseModel):
    """A durable server-side Kyber session.

    Three expiries coexist. ``presence_expires_at`` keeps a low-authority shell
    open for days; ``authority_expires_at`` is the hard ceiling on operator
    authority; ``idle_expires_at`` slides forward on use and closes an
    unattended session early.
    """

    session_id: str = Field(default_factory=lambda: _id("kses"))
    token_hash: str
    operator_id: str
    google_subject: Optional[str] = None
    device_id: Optional[str] = None
    status: SessionStatus = "restricted"
    authentication_methods: list[AuthenticationMethod] = Field(default_factory=list)
    authentication_strength: AuthenticationStrength = "none"
    environment: str = "local"
    presence_expires_at: Optional[str] = None
    authority_expires_at: Optional[str] = None
    idle_expires_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    last_seen_at: Optional[str] = None
    rotated_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None
    risk_state: DeviceRiskState = "ok"
    #: sha256 of the CSRF token handed to the browser for mutating requests.
    csrf_token_hash: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_authority(self) -> bool:
        """True when the session may exercise more than presence-level access."""
        return self.status == "active" and self.authentication_strength in (
            "device_bound",
            "stepped_up",
        )


class StepUpGrant(BaseModel):
    """A short-lived elevation proving a fresh WebAuthn assertion."""

    grant_id: str = Field(default_factory=lambda: _id("su"))
    session_id: str
    operator_id: str
    device_id: Optional[str] = None
    #: Optional narrowing: the capability or command this elevation was for.
    capability_id: Optional[str] = None
    reason: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    expires_at: str
    consumed_at: Optional[str] = None
    revoked_at: Optional[str] = None


class AuthenticationEvent(BaseModel):
    """Every authentication-relevant transition, success or failure.

    Failures deliberately record a coarse reason and never the submitted
    credential, so the table is safe to read widely during an investigation.
    """

    event_id: str = Field(default_factory=lambda: _id("kae"))
    event_type: AuthenticationEventType
    operator_id: Optional[str] = None
    google_subject: Optional[str] = None
    email: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    environment: Optional[str] = None
    outcome: Literal["succeeded", "failed"] = "succeeded"
    reason: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Tenant access scopes ──────────────────────────────────────────────────────

class AccessScope(BaseModel):
    """A durable, expiring, purpose-bound authorization to inspect one tenant.

    This replaces the previous in-process tenant-entry dictionary. A scope is
    bound to the session and device that opened it, so a stolen session on a
    different machine cannot ride an existing scope, and it names exactly one
    tenant — a request whose tenant parameter disagrees is denied rather than
    silently rescoped.
    """

    scope_id: str = Field(default_factory=lambda: _id("scope"))
    operator_id: str
    session_id: str
    device_id: Optional[str] = None
    environment: str
    tenant_id: str
    purpose: AccessScopePurpose
    reason: str
    ticket_reference: Optional[str] = None
    disclosure_level: int = int(DisclosureLevel.D3_TENANT_VISIBLE)
    status: AccessScopeStatus = "active"
    entered_at: str = Field(default_factory=now_iso)
    expires_at: str
    exited_at: Optional[str] = None
    revoked_at: Optional[str] = None
    policy_decision_id: Optional[str] = None
    rights_envelope_ref: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def disclosure(self) -> DisclosureLevel:
        return DisclosureLevel(self.disclosure_level)


# ── Access decisions ──────────────────────────────────────────────────────────

class KyberAccessDecision(BaseModel):
    """Durable evidence for one authorization decision on a Kyber route.

    ``policy_decision_id`` links back to the governance
    ``security_policy_decisions`` row written by the shared policy engine, so
    this table is the Kyber-specific detail of an existing decision rather than
    a parallel audit ledger.
    """

    decision_id: str = Field(default_factory=lambda: _id("kad"))
    policy_decision_id: Optional[str] = None
    operator_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    route_id: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    capability_id: Optional[str] = None
    action: Optional[str] = None
    action_class: int = 0
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    environment: Optional[str] = None
    tenant_id: Optional[str] = None
    scope_id: Optional[str] = None
    purpose: Optional[str] = None
    requested_disclosure: Optional[int] = None
    granted_disclosure: Optional[int] = None
    allowed: bool = False
    denial_reason: Optional[DenialReason] = None
    obligations: list[str] = Field(default_factory=list)
    step_up_required: bool = False
    approval_required: bool = False
    created_at: str = Field(default_factory=now_iso)
    expires_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KyberPrincipalView(BaseModel):
    """What ``GET /v1/kyber/me`` returns.

    The effective authority as the backend computed it. The frontend renders
    from this and never derives authority itself — no token decoding, no
    client-side role mapping.
    """

    operator_id: str
    email: str
    display_name: Optional[str] = None
    employment_status: EmploymentStatus
    environment: str
    session_id: str
    session_status: SessionStatus
    authentication_strength: AuthenticationStrength
    device_id: Optional[str] = None
    device_approval_state: Optional[DeviceApprovalState] = None
    role_template_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    max_disclosure: int = int(DisclosureLevel.D0_PLATFORM_TOPOLOGY)
    max_action_class: int = 0
    presence_expires_at: Optional[str] = None
    authority_expires_at: Optional[str] = None
    idle_expires_at: Optional[str] = None
    step_up_expires_at: Optional[str] = None
    active_scope: Optional[AccessScope] = None
    may_approve_devices: bool = False


__all__ = [
    "AccessScope",
    "AccessScopePurpose",
    "AccessScopeStatus",
    "AuthenticationEvent",
    "AuthenticationEventType",
    "AuthenticationMethod",
    "AuthenticationStrength",
    "CapabilityGrant",
    "DenialReason",
    "DeviceApprovalEvent",
    "DeviceApprovalState",
    "DeviceProofKey",
    "DeviceRiskState",
    "EmploymentStatus",
    "InvitationStatus",
    "KyberAccessDecision",
    "KyberPrincipalView",
    "RoleBinding",
    "SessionStatus",
    "StepUpGrant",
    "TrustedDevice",
    "WebAuthnCredential",
    "WorkforceInvitation",
    "WorkforcePrincipal",
    "WorkforceSession",
    "now_iso",
]
