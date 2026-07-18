/**
 * Kyber operator capability fetcher. Reads GET /v1/kyber/capabilities (the
 * operator capability read) and adapts it into the shared `Capabilities` shape
 * consumed by the capability provider, navigation, and route guards.
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

const operatorEnvelopeSchema = z.object({
  data: z.object({
    release: releaseSchema,
    feature_flags: z.record(z.boolean()),
    extraction_defense_mode: z.string().nullable().optional(),
    evaluated_at: z.string(),
  }),
  status: z.string(),
  timestamp: z.string(),
});

export async function fetchOperatorCapabilities(): Promise<Capabilities> {
  const res = await restClient.get('/v1/kyber/capabilities', operatorEnvelopeSchema);
  const op = res.data;
  return {
    tenant_id: 'operator',
    release: op.release,
    profile_sub_resources: [],
    providers: [],
    consent_purposes_granted: [],
    consent_purposes_all: [],
    feature_flags: op.feature_flags,
    evaluated_at: op.evaluated_at,
  };
}
