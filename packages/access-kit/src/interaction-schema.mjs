import * as z from 'zod/v4';

export const interactionSchema = z.object({
  version: z.literal('1'),
  operation: z.enum(['query', 'observe', 'auth', 'write']),
  status_class: z.enum(['successful', 'denied', 'blocked', 'degraded', 'failed']),
  request_id: z.string().min(1),
  api_request_id: z.string().min(1).optional(),
  http_status: z.number().int().nullable(),
  error_code: z.string().min(1).optional(),
  references: z.record(z.string().max(64), z.string().max(256)),
});

export const accountContextSchema = z.object({
  name: z.string().max(256).nullable(),
  plan: z.object({
    plan_id: z.string().max(128).nullable(),
    display_name: z.string().max(128).nullable(),
    monthly_quota: z.number().int().nullable(),
    burst_rpm: z.number().int().nullable(),
  }).nullable(),
  billing: z.object({
    subscription_status: z.string().max(64).nullable(),
    current_period_end: z.string().max(64).nullable(),
  }).nullable(),
  api_key_count: z.number().int().nullable(),
  is_admin: z.boolean().nullable(),
});
