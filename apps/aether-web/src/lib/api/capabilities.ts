/**
 * Tenant capability fetcher. Reads GET /v1/capabilities (the tenant capability
 * contract) and validates it into the shared `Capabilities` shape consumed by
 * the capability provider, navigation, and route guards.
 */

import { z } from 'zod';
import type { Capabilities } from '@aether/ui';
import { restClient } from './rest/client';

const enforcementSchema = z.object({
  policy_enforcement: z.boolean(),
  route_registry_enforced: z.boolean(),
  kyber_operator_gate: z.boolean(),
});

const releaseSchema = z.object({
  deployment_profile: z.string(),
  environment: z.string(),
  release_class: z.string().nullable(),
  enforcement: enforcementSchema,
  enabled_route_prefixes: z.array(z.string()),
  excluded_domains: z.array(z.string()),
});

// The backend always emits all provider fields (Pydantic fills defaults), so
// these are required here — avoids injecting `undefined` under the app's
// exactOptionalPropertyTypes.
const providerSchema = z.object({
  id: z.string(),
  category: z.string(),
  status: z.string(),
  last_successful_sync: z.string().nullable(),
  error_count: z.number(),
  staleness_label: z.string(),
  circuit_breaker: z.string(),
});

const capabilitiesEnvelopeSchema = z.object({
  data: z.object({
    tenant_id: z.string(),
    release: releaseSchema,
    profile_sub_resources: z.array(z.string()),
    providers: z.array(providerSchema),
    consent_purposes_granted: z.array(z.string()),
    consent_purposes_all: z.array(z.string()),
    feature_flags: z.record(z.boolean()),
    evaluated_at: z.string(),
  }),
  status: z.string(),
  timestamp: z.string(),
});

export async function fetchTenantCapabilities(): Promise<Capabilities> {
  const res = await restClient.get('/v1/capabilities', capabilitiesEnvelopeSchema);
  return res.data;
}
