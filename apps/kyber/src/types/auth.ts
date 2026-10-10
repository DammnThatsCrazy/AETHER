/**
 * Kyber authentication & authorization contract types.
 *
 * These mirror the backend `KyberPrincipalView` / session / device / scope
 * payloads exactly, in the backend's snake_case wire shape.
 *
 * NOTHING here is derived in the browser. There is deliberately:
 *   - no token type (the session is a `__Host-kyber_session` HttpOnly cookie
 *     the browser cannot read),
 *   - no JWT/claims type (the frontend never decodes a token),
 *   - no client-side role union (roles are `role_template_ids` handed down by
 *     the backend, never inferred from a `groups` claim).
 *
 * Everything below arrives from the server and is treated as advisory display
 * state; the backend remains the sole authority on what an operator may do.
 */

// ── Principal ────────────────────────────────────────────────────────────────

export type EmploymentStatus = 'invited' | 'active' | 'suspended' | 'offboarded';

export type KyberSessionStatus =
  | 'restricted'
  | 'active'
  | 'risk_limited'
  | 'revoked'
  | 'expired'
  | 'locked';

export type AuthenticationStrength =
  | 'none'
  | 'identity_only'
  | 'device_bound'
  | 'stepped_up';

export type DeviceApprovalState =
  | 'pending'
  | 'approved'
  | 'suspended'
  | 'revoked'
  | 'expired';

export type ScopePurpose =
  | 'incident_response'
  | 'customer_support'
  | 'compliance_audit'
  | 'security_investigation'
  | 'data_request'
  | 'diagnostics'
  | 'break_glass'
  | 'product_validation';

export type AccessScopeStatus = 'active' | 'expired' | 'exited' | 'revoked';

/** Capability identifiers are opaque backend strings, e.g. `kyber.tenant.mirror.read`. */
export type CapabilityId = string;

export interface AccessScope {
  readonly scope_id: string;
  readonly operator_id: string;
  readonly session_id: string;
  readonly device_id: string | null;
  readonly environment: string;
  readonly tenant_id: string;
  readonly purpose: ScopePurpose;
  readonly reason: string;
  readonly ticket_reference: string | null;
  readonly disclosure_level: number;
  readonly status: AccessScopeStatus;
  readonly entered_at: string;
  readonly expires_at: string | null;
  readonly exited_at: string | null;
}

export interface KyberPrincipalView {
  readonly operator_id: string;
  readonly email: string;
  readonly display_name: string | null;
  readonly employment_status: EmploymentStatus;
  readonly environment: string;
  readonly session_id: string;
  readonly session_status: KyberSessionStatus;
  readonly authentication_strength: AuthenticationStrength;
  readonly device_id: string | null;
  readonly device_approval_state: DeviceApprovalState | null;
  readonly role_template_ids: readonly string[];
  readonly capabilities: readonly CapabilityId[];
  /** 0..5 — maximum disclosure level the backend will serve this principal. */
  readonly max_disclosure: number;
  /** 0..5 — maximum mutation/action class the backend will accept. */
  readonly max_action_class: number;
  readonly presence_expires_at: string | null;
  readonly authority_expires_at: string | null;
  readonly idle_expires_at: string | null;
  readonly step_up_expires_at: string | null;
  readonly active_scope: AccessScope | null;
  readonly may_approve_devices: boolean;
}

// ── Session ──────────────────────────────────────────────────────────────────

export interface KyberSessionView {
  readonly session_id: string;
  readonly operator_id: string;
  readonly status: KyberSessionStatus;
  readonly authentication_strength: AuthenticationStrength;
  readonly environment: string;
  readonly device_id: string | null;
  readonly device_approval_state: DeviceApprovalState | null;
  readonly issued_at: string | null;
  readonly presence_expires_at: string | null;
  readonly authority_expires_at: string | null;
  readonly idle_expires_at: string | null;
  readonly step_up_expires_at: string | null;
  readonly step_up_required: boolean;
  readonly risk_reasons: readonly string[];
}

// ── Devices ──────────────────────────────────────────────────────────────────

export interface KyberDevice {
  readonly device_id: string;
  readonly operator_id: string;
  readonly display_name: string | null;
  readonly approval_state: DeviceApprovalState;
  readonly platform: string | null;
  readonly browser: string | null;
  readonly user_agent: string | null;
  readonly requested_by: string | null;
  readonly requested_at: string | null;
  readonly approved_by: string | null;
  readonly approved_at: string | null;
  readonly last_seen_at: string | null;
  readonly has_proof_key: boolean;
  readonly is_current_device: boolean;
}

/** Server-issued WebAuthn options, already JSON-encoded (base64url binaries). */
export interface WebAuthnRegistrationOptions {
  readonly challenge: string;
  readonly rp: { readonly id: string | null; readonly name: string };
  readonly user: { readonly id: string; readonly name: string; readonly displayName: string };
  readonly pubKeyCredParams: readonly { readonly type: 'public-key'; readonly alg: number }[];
  readonly timeout: number | null;
  readonly attestation: string | null;
  readonly excludeCredentials: readonly { readonly id: string; readonly type: 'public-key' }[];
  readonly userVerification: string | null;
  readonly residentKey: string | null;
}

export interface WebAuthnAssertionOptions {
  readonly challenge: string;
  readonly rpId: string | null;
  readonly timeout: number | null;
  readonly userVerification: string | null;
  readonly allowCredentials: readonly { readonly id: string; readonly type: 'public-key' }[];
}

export interface DeviceProofChallenge {
  readonly challenge_id: string;
  readonly challenge: string;
  readonly expires_at: string | null;
}

// ── Workforce ────────────────────────────────────────────────────────────────

export interface WorkforcePrincipal {
  readonly operator_id: string;
  readonly email: string;
  readonly display_name: string | null;
  readonly employment_status: EmploymentStatus;
  readonly role_template_ids: readonly string[];
  readonly environment: string;
  readonly last_active_at: string | null;
  readonly device_count: number;
}

export type InvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

export interface WorkforceInvitation {
  readonly invitation_id: string;
  readonly email: string;
  readonly role_template_ids: readonly string[];
  readonly status: InvitationStatus;
  readonly invited_by: string | null;
  readonly invited_at: string | null;
  readonly expires_at: string | null;
  readonly accepted_at: string | null;
}

// ── Audit ────────────────────────────────────────────────────────────────────

export interface KyberAuditEvent {
  readonly event_id: string;
  readonly event_type: string;
  readonly operator_id: string | null;
  readonly session_id: string | null;
  readonly device_id: string | null;
  readonly tenant_id: string | null;
  readonly outcome: string;
  readonly reason: string | null;
  readonly occurred_at: string;
}
