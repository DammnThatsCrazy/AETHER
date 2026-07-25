/**
 * Zod schemas for the Kyber auth/authz wire contract.
 *
 * Parsing happens at the network boundary and nowhere else. Unknown enum
 * members are NOT silently coerced to a permissive value — an unrecognised
 * `session_status` or `approval_state` is a contract break we want surfaced,
 * except where explicitly widened below for forward compatibility on
 * non-security-bearing fields.
 */

import { z } from 'zod';
import type {
  AccessScope,
  DeviceProofChallenge,
  KyberAuditEvent,
  KyberDevice,
  KyberPrincipalView,
  KyberSessionView,
  WebAuthnAssertionOptions,
  WebAuthnRegistrationOptions,
  WorkforceInvitation,
  WorkforcePrincipal,
} from '@kyber/types';

const nullableString = z.string().nullable().default(null);

export const employmentStatusSchema = z.enum([
  'invited',
  'active',
  'suspended',
  'offboarded',
]);

export const sessionStatusSchema = z.enum([
  'restricted',
  'active',
  'risk_limited',
  'revoked',
  'expired',
  'locked',
]);

export const authenticationStrengthSchema = z.enum([
  'none',
  'identity_only',
  'device_bound',
  'stepped_up',
]);

export const deviceApprovalStateSchema = z.enum([
  'pending',
  'approved',
  'suspended',
  'revoked',
  'expired',
]);

export const scopePurposeSchema = z.enum([
  'incident_response',
  'customer_support',
  'compliance_audit',
  'security_investigation',
  'data_request',
  'diagnostics',
  'break_glass',
  'product_validation',
]);

export const accessScopeStatusSchema = z.enum(['active', 'expired', 'exited', 'revoked']);

export const accessScopeSchema = z.object({
  scope_id: z.string(),
  operator_id: z.string(),
  session_id: z.string(),
  device_id: nullableString,
  environment: z.string(),
  tenant_id: z.string(),
  purpose: scopePurposeSchema,
  reason: z.string(),
  ticket_reference: nullableString,
  disclosure_level: z.number(),
  status: accessScopeStatusSchema,
  entered_at: z.string(),
  expires_at: nullableString,
  exited_at: nullableString,
});

export const principalSchema = z.object({
  operator_id: z.string(),
  email: z.string(),
  display_name: nullableString,
  employment_status: employmentStatusSchema,
  environment: z.string(),
  session_id: z.string(),
  session_status: sessionStatusSchema,
  authentication_strength: authenticationStrengthSchema,
  device_id: nullableString,
  device_approval_state: deviceApprovalStateSchema.nullable().default(null),
  role_template_ids: z.array(z.string()).default([]),
  capabilities: z.array(z.string()).default([]),
  max_disclosure: z.number().default(0),
  max_action_class: z.number().default(0),
  presence_expires_at: nullableString,
  authority_expires_at: nullableString,
  idle_expires_at: nullableString,
  step_up_expires_at: nullableString,
  active_scope: accessScopeSchema.nullable().default(null),
  may_approve_devices: z.boolean().default(false),
});

export const sessionSchema = z.object({
  session_id: z.string(),
  operator_id: z.string(),
  status: sessionStatusSchema,
  authentication_strength: authenticationStrengthSchema,
  environment: z.string().default(''),
  device_id: nullableString,
  device_approval_state: deviceApprovalStateSchema.nullable().default(null),
  issued_at: nullableString,
  presence_expires_at: nullableString,
  authority_expires_at: nullableString,
  idle_expires_at: nullableString,
  step_up_expires_at: nullableString,
  step_up_required: z.boolean().default(false),
  risk_reasons: z.array(z.string()).default([]),
});

export const deviceSchema = z.object({
  device_id: z.string(),
  operator_id: z.string(),
  display_name: nullableString,
  approval_state: deviceApprovalStateSchema,
  platform: nullableString,
  browser: nullableString,
  user_agent: nullableString,
  requested_by: nullableString,
  requested_at: nullableString,
  approved_by: nullableString,
  approved_at: nullableString,
  last_seen_at: nullableString,
  has_proof_key: z.boolean().default(false),
  is_current_device: z.boolean().default(false),
});

const credentialDescriptorSchema = z.object({
  id: z.string(),
  type: z.literal('public-key').default('public-key'),
});

export const registrationOptionsSchema = z.object({
  challenge: z.string(),
  rp: z.object({ id: nullableString, name: z.string().default('Kyber') }),
  user: z.object({ id: z.string(), name: z.string(), displayName: z.string() }),
  pubKeyCredParams: z
    .array(z.object({ type: z.literal('public-key').default('public-key'), alg: z.number() }))
    .default([{ type: 'public-key', alg: -7 }]),
  timeout: z.number().nullable().default(null),
  attestation: nullableString,
  excludeCredentials: z.array(credentialDescriptorSchema).default([]),
  userVerification: nullableString,
  residentKey: nullableString,
});

export const assertionOptionsSchema = z.object({
  challenge: z.string(),
  rpId: nullableString,
  timeout: z.number().nullable().default(null),
  userVerification: nullableString,
  allowCredentials: z.array(credentialDescriptorSchema).default([]),
});

export const proofChallengeSchema = z.object({
  challenge_id: z.string(),
  challenge: z.string(),
  expires_at: nullableString,
});

export const workforcePrincipalSchema = z.object({
  operator_id: z.string(),
  email: z.string(),
  display_name: nullableString,
  employment_status: employmentStatusSchema,
  role_template_ids: z.array(z.string()).default([]),
  environment: z.string().default(''),
  last_active_at: nullableString,
  device_count: z.number().default(0),
});

export const invitationSchema = z.object({
  invitation_id: z.string(),
  email: z.string(),
  role_template_ids: z.array(z.string()).default([]),
  status: z.enum(['pending', 'accepted', 'revoked', 'expired']),
  invited_by: nullableString,
  invited_at: nullableString,
  expires_at: nullableString,
  accepted_at: nullableString,
});

export const auditEventSchema = z.object({
  event_id: z.string(),
  event_type: z.string(),
  operator_id: nullableString,
  session_id: nullableString,
  device_id: nullableString,
  tenant_id: nullableString,
  outcome: z.string(),
  reason: nullableString,
  occurred_at: z.string(),
});

/**
 * Backends in this repo wrap collections either as a bare array or as
 * `{items: [...]}` / `{data: [...]}`. Accept all three so the frontend does not
 * break on an envelope decision made in a parallel PR.
 */
export function collection<T>(item: z.ZodType<T>): z.ZodType<T[]> {
  return z.union([
    z.array(item),
    z.object({ items: z.array(item) }).transform((v) => v.items),
    z.object({ data: z.array(item) }).transform((v) => v.data),
  ]);
}

/** Unwrap `{data: X}` envelopes while tolerating bare objects. */
export function envelope<T>(inner: z.ZodType<T>): z.ZodType<T> {
  return z.union([inner, z.object({ data: inner }).transform((v) => v.data)]);
}

// Compile-time contract assertions: if a schema output drifts away from the
// declared wire type in `@kyber/types`, these assignments fail `tsc`.
export const parsePrincipal = (raw: unknown): KyberPrincipalView =>
  envelope(principalSchema).parse(raw);
export const parseSession = (raw: unknown): KyberSessionView => envelope(sessionSchema).parse(raw);
export const parseAccessScope = (raw: unknown): AccessScope => envelope(accessScopeSchema).parse(raw);
export const parseNullableAccessScope = (raw: unknown): AccessScope | null =>
  envelope(accessScopeSchema.nullable()).parse(raw);
export const parseDevices = (raw: unknown): KyberDevice[] => collection(deviceSchema).parse(raw);
export const parseDevice = (raw: unknown): KyberDevice => envelope(deviceSchema).parse(raw);
export const parseScopes = (raw: unknown): AccessScope[] => collection(accessScopeSchema).parse(raw);
export const parseRegistrationOptions = (raw: unknown): WebAuthnRegistrationOptions =>
  envelope(registrationOptionsSchema).parse(raw);
export const parseAssertionOptions = (raw: unknown): WebAuthnAssertionOptions =>
  envelope(assertionOptionsSchema).parse(raw);
export const parseProofChallenge = (raw: unknown): DeviceProofChallenge =>
  envelope(proofChallengeSchema).parse(raw);
export const parseWorkforcePrincipals = (raw: unknown): WorkforcePrincipal[] =>
  collection(workforcePrincipalSchema).parse(raw);
export const parseInvitations = (raw: unknown): WorkforceInvitation[] =>
  collection(invitationSchema).parse(raw);
export const parseInvitation = (raw: unknown): WorkforceInvitation =>
  envelope(invitationSchema).parse(raw);
export const parseAuditEvents = (raw: unknown): KyberAuditEvent[] =>
  collection(auditEventSchema).parse(raw);
