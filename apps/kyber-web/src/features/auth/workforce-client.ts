/**
 * Workforce + audit reads for the security console.
 *
 * Every call is cookie-authenticated and CSRF-protected by `requestJson`.
 * Membership, role templates and invitations are entirely backend-owned; this
 * module only renders what it is told and posts intents back.
 */

import {
  KYBER_AUDIT_ENDPOINTS,
  KYBER_WORKFORCE_ENDPOINTS,
  requestJson,
  requestVoid,
} from '@kyber/lib/auth';
import type { KyberAuditEvent, WorkforceInvitation, WorkforcePrincipal } from '@kyber/types';
import { parseAuditEvents, parseInvitation, parseInvitations, parseWorkforcePrincipals } from './schemas';

export async function fetchWorkforcePrincipals(signal?: AbortSignal): Promise<WorkforcePrincipal[]> {
  return requestJson(KYBER_WORKFORCE_ENDPOINTS.principals, parseWorkforcePrincipals, { signal });
}

export async function fetchInvitations(signal?: AbortSignal): Promise<WorkforceInvitation[]> {
  return requestJson(KYBER_WORKFORCE_ENDPOINTS.invitations, parseInvitations, { signal });
}

export interface CreateInvitationInput {
  readonly email: string;
  readonly role_template_ids: readonly string[];
  readonly reason: string;
}

export async function createInvitation(input: CreateInvitationInput): Promise<WorkforceInvitation> {
  return requestJson(KYBER_WORKFORCE_ENDPOINTS.invitations, parseInvitation, {
    method: 'POST',
    body: input,
  });
}

export async function revokeInvitation(invitationId: string): Promise<void> {
  await requestVoid(KYBER_WORKFORCE_ENDPOINTS.revokeInvitation(invitationId), { method: 'POST' });
}

export async function acceptInvitation(invitationId: string): Promise<void> {
  await requestVoid(KYBER_WORKFORCE_ENDPOINTS.acceptInvitation(invitationId), { method: 'POST' });
}

export interface AuditQuery {
  readonly limit?: number | undefined;
  readonly event_type?: string | undefined;
  readonly operator_id?: string | undefined;
}

export async function fetchAuditEvents(
  query: AuditQuery = {},
  signal?: AbortSignal,
): Promise<KyberAuditEvent[]> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  if (query.event_type !== undefined && query.event_type !== '') {
    params.set('event_type', query.event_type);
  }
  if (query.operator_id !== undefined && query.operator_id !== '') {
    params.set('operator_id', query.operator_id);
  }
  const suffix = params.toString();
  const path = suffix ? `${KYBER_AUDIT_ENDPOINTS.events}?${suffix}` : KYBER_AUDIT_ENDPOINTS.events;
  return requestJson(path, parseAuditEvents, { signal });
}
