/**
 * Tenant access-scope API.
 *
 * A scope is the backend's record of "this operator is looking at this tenant,
 * for this reason, until this time". The frontend can request one and display
 * it; it cannot grant one, extend one, or read tenant data without one.
 */

import { KYBER_SCOPE_ENDPOINTS, requestJson, requestVoid } from '@kyber/lib/auth';
import type { AccessScope, ScopePurpose } from '@kyber/types';
import { parseAccessScope, parseNullableAccessScope, parseScopes } from './schemas';

export interface EnterScopeInput {
  readonly tenant_id: string;
  readonly purpose: ScopePurpose;
  readonly reason: string;
  readonly ticket_reference: string | null;
  readonly disclosure_level: number;
  readonly requested_ttl_seconds: number | null;
}

export async function enterScope(input: EnterScopeInput): Promise<AccessScope> {
  return requestJson(KYBER_SCOPE_ENDPOINTS.enter, parseAccessScope, {
    method: 'POST',
    body: input,
  });
}

export async function fetchCurrentScope(signal?: AbortSignal): Promise<AccessScope | null> {
  return requestJson(KYBER_SCOPE_ENDPOINTS.current, parseNullableAccessScope, { signal });
}

export async function fetchScopeHistory(signal?: AbortSignal): Promise<AccessScope[]> {
  return requestJson(KYBER_SCOPE_ENDPOINTS.list, parseScopes, { signal });
}

export async function exitScope(scopeId: string): Promise<void> {
  await requestVoid(KYBER_SCOPE_ENDPOINTS.exit(scopeId), { method: 'DELETE' });
}

export const SCOPE_PURPOSES: readonly ScopePurpose[] = [
  'incident_response',
  'customer_support',
  'compliance_audit',
  'security_investigation',
  'data_request',
  'diagnostics',
  'break_glass',
  'product_validation',
];

export function describePurpose(purpose: ScopePurpose): string {
  return purpose.replace(/_/g, ' ');
}
