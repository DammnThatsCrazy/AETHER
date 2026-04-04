/**
 * SHIKI API Endpoints — maps to real Aether backend routes.
 * All responses are wrapped in { data, status, timestamp }.
 * Extract `.data` for the actual payload.
 */
import { z } from 'zod';
import { restClient } from '@shiki/lib/api';
import { log } from '@shiki/lib/logging';

// ─── Response wrapper ────────────────────────────────────────────
const apiResponseSchema = <T extends z.ZodType>(dataSchema: T) =>
  z.object({
    data: dataSchema,
    status: z.string(),
    timestamp: z.string(),
  });

// ─── Shared schemas ──────────────────────────────────────────────
const healthCheckSchema = z.object({
  status: z.string(),
  uptime: z.number().optional(),
  version: z.string().optional(),
  services: z.record(z.object({
    status: z.string(),
    latency_ms: z.number().optional(),
    error: z.string().optional().nullable(),
  })).optional(),
  timestamp: z.string().optional(),
}).passthrough();

const errorEntrySchema = z.object({
  fingerprint: z.string(),
  message: z.string(),
  count: z.number(),
  first_seen: z.string(),
  last_seen: z.string(),
  severity: z.string(),
  service: z.string().optional(),
  category: z.string().optional(),
  resolved: z.boolean().optional(),
  suppressed: z.boolean().optional(),
}).passthrough();

const circuitBreakerSchema = z.record(z.object({
  state: z.string(),
  failures: z.number(),
  last_failure: z.string().optional().nullable(),
  next_retry: z.string().optional().nullable(),
}).passthrough());

const dashboardSummarySchema = z.object({
  sessions_last_24h: z.number().optional(),
  events_last_24h: z.number().optional(),
  unique_users_last_24h: z.number().optional(),
  top_events: z.array(z.object({ name: z.string(), count: z.number() })).optional(),
}).passthrough();

const alertSchema = z.object({
  id: z.string().optional(),
  name: z.string(),
  condition: z.string().optional(),
  channels: z.array(z.string()).optional(),
  severity: z.string().optional(),
  active: z.boolean().optional(),
  created_at: z.string().optional(),
}).passthrough();

const agentStatusSchema = z.object({
  active_workers: z.number().optional(),
  queued_tasks: z.number().optional(),
  completed_tasks: z.number().optional(),
  failed_tasks: z.number().optional(),
  kill_switch: z.boolean().optional(),
  workers: z.array(z.object({
    worker_type: z.string(),
    status: z.string(),
    current_task: z.string().optional().nullable(),
  }).passthrough()).optional(),
}).passthrough();

const taskSchema = z.object({
  task_id: z.string(),
  worker_type: z.string(),
  priority: z.string(),
  status: z.string(),
  created_at: z.string(),
  started_at: z.string().optional().nullable(),
  completed_at: z.string().optional().nullable(),
  result: z.unknown().optional().nullable(),
  error: z.string().optional().nullable(),
}).passthrough();

const auditRecordSchema = z.object({
  records: z.array(z.unknown()),
  total: z.number(),
});

const entityClusterSchema = z.object({
  entity_id: z.string(),
  cluster_size: z.number(),
  linked_entities: z.array(z.object({
    id: z.string(),
    type: z.string(),
    properties: z.record(z.unknown()).optional(),
  }).passthrough()),
  identity_features: z.array(z.unknown()).optional(),
  computed_at: z.string(),
}).passthrough();

const walletProfileSchema = z.object({
  wallet_address: z.string(),
  risk: z.record(z.unknown()).optional(),
  features: z.record(z.unknown()).optional(),
  graph: z.object({
    neighbor_count: z.number(),
    neighbors: z.array(z.object({ id: z.string(), type: z.string() }).passthrough()),
  }).optional(),
  computed_at: z.string(),
}).passthrough();

const profileSchema = z.object({
  user_id: z.string().optional(),
  events: z.array(z.unknown()).optional(),
  connections: z.array(z.unknown()).optional(),
  timeline: z.array(z.unknown()).optional(),
  intelligence: z.record(z.unknown()).optional(),
  identifiers: z.array(z.unknown()).optional(),
}).passthrough();

const webhookSchema = z.object({
  id: z.string().optional(),
  url: z.string(),
  events: z.array(z.string()),
  active: z.boolean().optional(),
}).passthrough();

const populationSummarySchema = z.object({
  total_groups: z.number().optional(),
  total_members: z.number().optional(),
  by_type: z.record(z.number()).optional(),
  computed_at: z.string().optional(),
}).passthrough();

const behavioralSummarySchema = z.object({
  total_signals: z.number().optional(),
  by_family: z.record(z.number()).optional(),
  top_families: z.array(z.unknown()).optional(),
  computed_at: z.string().optional(),
}).passthrough();

const diagnosticReportSchema = z.object({
  health: healthCheckSchema.optional(),
  errors: z.array(errorEntrySchema).optional(),
  circuit_breakers: circuitBreakerSchema.optional(),
  services: z.record(z.unknown()).optional(),
}).passthrough();

const alertsListSchema = z.object({
  alerts: z.array(alertSchema),
  count: z.number(),
  queried_at: z.string().optional(),
});

const eventsQuerySchema = z.object({
  data: z.array(z.unknown()),
  pagination: z.object({
    total: z.number(),
    limit: z.number(),
    has_more: z.boolean(),
  }).optional(),
}).passthrough();

const graphqlResponseSchema = z.object({
  data: z.unknown().nullable(),
  errors: z.array(z.object({ message: z.string() }).passthrough()).optional().nullable(),
});

// ─── API Client ──────────────────────────────────────────────────

export const api = {
  // ── Analytics ──
  analytics: {
    dashboardSummary: () =>
      restClient.get('/v1/analytics/dashboard/summary', apiResponseSchema(dashboardSummarySchema))
        .then(r => r.data),

    queryEvents: (query: { event_type?: string; start_date?: string; end_date?: string; limit?: number }) =>
      restClient.post('/v1/analytics/events/query', apiResponseSchema(eventsQuerySchema), query)
        .then(r => r.data),

    getEvent: (eventId: string) =>
      restClient.get(`/v1/analytics/events/${eventId}`, apiResponseSchema(z.unknown()))
        .then(r => r.data),

    graphql: (query: string, variables?: Record<string, unknown>) =>
      restClient.post('/v1/analytics/graphql', apiResponseSchema(graphqlResponseSchema), { query, variables })
        .then(r => r.data),
  },

  // ── Diagnostics ──
  diagnostics: {
    health: () =>
      restClient.get('/v1/diagnostics/health', apiResponseSchema(healthCheckSchema))
        .then(r => r.data),

    errors: (params?: { severity?: string; limit?: number; resolved?: boolean }) => {
      const qs = new URLSearchParams();
      if (params?.severity) qs.set('severity', params.severity);
      if (params?.limit) qs.set('limit', String(params.limit));
      if (params?.resolved !== undefined) qs.set('resolved', String(params.resolved));
      const query = qs.toString();
      return restClient.get(`/v1/diagnostics/errors${query ? `?${query}` : ''}`, apiResponseSchema(z.object({ errors: z.array(errorEntrySchema), count: z.number() })))
        .then(r => r.data);
    },

    report: () =>
      restClient.get('/v1/diagnostics/report', apiResponseSchema(diagnosticReportSchema))
        .then(r => r.data),

    resolveError: (fingerprint: string) =>
      restClient.post(`/v1/diagnostics/errors/${fingerprint}/resolve`, apiResponseSchema(z.object({ fingerprint: z.string(), resolved: z.boolean() }))),

    suppressError: (fingerprint: string) =>
      restClient.post(`/v1/diagnostics/errors/${fingerprint}/suppress`, apiResponseSchema(z.object({ fingerprint: z.string(), suppressed: z.boolean() }))),

    circuitBreakers: () =>
      restClient.get('/v1/diagnostics/circuit-breakers', apiResponseSchema(circuitBreakerSchema))
        .then(r => r.data),
  },

  // ── Intelligence ──
  intelligence: {
    alerts: (limit = 50) =>
      restClient.get(`/v1/intelligence/alerts?limit=${limit}`, apiResponseSchema(alertsListSchema))
        .then(r => r.data),

    walletRisk: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/risk`, apiResponseSchema(z.unknown()))
        .then(r => r.data),

    walletProfile: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/profile`, apiResponseSchema(walletProfileSchema))
        .then(r => r.data),

    entityCluster: (entityId: string) =>
      restClient.get(`/v1/intelligence/entity/${entityId}/cluster`, apiResponseSchema(entityClusterSchema))
        .then(r => r.data),

    protocolAnalytics: (protocolId: string) =>
      restClient.get(`/v1/intelligence/protocol/${protocolId}/analytics`, apiResponseSchema(z.unknown()))
        .then(r => r.data),
  },

  // ── Agent / Controllers ──
  agent: {
    status: () =>
      restClient.get('/v1/agent/status', apiResponseSchema(agentStatusSchema))
        .then(r => r.data),

    tasks: (taskId?: string) =>
      taskId
        ? restClient.get(`/v1/agent/tasks/${taskId}`, apiResponseSchema(taskSchema)).then(r => r.data)
        : restClient.get('/v1/agent/audit', apiResponseSchema(auditRecordSchema)).then(r => r.data),

    audit: (limit = 50) =>
      restClient.get(`/v1/agent/audit?limit=${limit}`, apiResponseSchema(auditRecordSchema))
        .then(r => r.data),

    submitTask: (workerType: string, priority: string, payload: Record<string, unknown>) =>
      restClient.post('/v1/agent/tasks', apiResponseSchema(taskSchema), { worker_type: workerType, priority, payload }),

    killSwitch: (action: string) =>
      restClient.post('/v1/agent/kill-switch', apiResponseSchema(z.object({ kill_switch: z.boolean(), action: z.string() })), { action }),

    agentGraph: (agentId: string, layer = 'all') =>
      restClient.get(`/v1/agent/${agentId}/graph?layer=${layer}`, apiResponseSchema(z.unknown()))
        .then(r => r.data),

    agentTrust: (agentId: string) =>
      restClient.get(`/v1/agent/${agentId}/trust`, apiResponseSchema(z.unknown()))
        .then(r => r.data),
  },

  // ── Profile 360 ──
  profile: {
    full: (userId: string) =>
      restClient.get(`/v1/profile/${userId}?include_timeline=true&include_graph=true&include_intelligence=true`, apiResponseSchema(profileSchema))
        .then(r => r.data),

    timeline: (userId: string, limit = 100) =>
      restClient.get(`/v1/profile/${userId}/timeline?limit=${limit}`, apiResponseSchema(z.object({ user_id: z.string(), events: z.array(z.unknown()), count: z.number() })))
        .then(r => r.data),

    graph: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/graph`, apiResponseSchema(z.unknown()))
        .then(r => r.data),

    resolve: (params: { wallet?: string; email?: string; device?: string }) => {
      const qs = new URLSearchParams();
      if (params.wallet) qs.set('wallet', params.wallet);
      if (params.email) qs.set('email', params.email);
      if (params.device) qs.set('device', params.device);
      return restClient.get(`/v1/profile/resolve?${qs.toString()}`, apiResponseSchema(z.object({ resolved_user_id: z.string() })))
        .then(r => r.data);
    },
  },

  // ── Identity ──
  identity: {
    getProfile: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}`, apiResponseSchema(profileSchema))
        .then(r => r.data),

    graphNeighborhood: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}/graph`, apiResponseSchema(z.object({ user_id: z.string(), connections: z.array(z.unknown()) }).passthrough()))
        .then(r => r.data),
  },

  // ── Notifications ──
  notifications: {
    listAlerts: () =>
      restClient.get('/v1/notifications/alerts', apiResponseSchema(z.array(alertSchema)))
        .then(r => r.data),

    createAlert: (alert: { name: string; condition: string; channels: string[]; recipients?: string[] }) =>
      restClient.post('/v1/notifications/alerts', apiResponseSchema(alertSchema), alert),

    listWebhooks: () =>
      restClient.get('/v1/notifications/webhooks', apiResponseSchema(z.array(webhookSchema)))
        .then(r => r.data),

    createWebhook: (webhook: { url: string; events: string[]; secret?: string }) =>
      restClient.post('/v1/notifications/webhooks', apiResponseSchema(webhookSchema), webhook),

    deleteWebhook: (webhookId: string) =>
      restClient.delete(`/v1/notifications/webhooks/${webhookId}`, apiResponseSchema(z.object({ deleted: z.boolean() }))),
  },

  // ── Population ──
  population: {
    summary: () =>
      restClient.get('/v1/population/summary', apiResponseSchema(populationSummarySchema))
        .then(r => r.data),

    groups: (type?: string, limit = 50) => {
      const qs = new URLSearchParams();
      if (type) qs.set('population_type', type);
      qs.set('limit', String(limit));
      return restClient.get(`/v1/population/groups?${qs.toString()}`, apiResponseSchema(z.object({ groups: z.array(z.unknown()), count: z.number() })))
        .then(r => r.data);
    },
  },

  // ── Behavioral ──
  behavioral: {
    summary: () =>
      restClient.get('/v1/behavioral/summary', apiResponseSchema(behavioralSummarySchema))
        .then(r => r.data),

    entity: (entityId: string) =>
      restClient.get(`/v1/behavioral/entity/${entityId}`, apiResponseSchema(z.unknown()))
        .then(r => r.data),

    signals: (entityId: string, limit = 50) =>
      restClient.get(`/v1/behavioral/entity/${entityId}/signals?limit=${limit}`, apiResponseSchema(z.object({ entity_id: z.string(), signals: z.array(z.unknown()), count: z.number() })))
        .then(r => r.data),
  },

  // ── Automation overview ──
  automation: {
    overview: () =>
      restClient.get('/v1/automation/overview', apiResponseSchema(z.unknown()))
        .then(r => r.data),

    insights: () =>
      restClient.get('/v1/automation/insights', apiResponseSchema(z.unknown()))
        .then(r => r.data),
  },
};

// Helper to safely call API with fallback
export async function apiCall<T>(
  fetcher: () => Promise<T>,
  fallback: T,
  label: string,
): Promise<{ data: T; fromApi: boolean }> {
  try {
    const data = await fetcher();
    return { data, fromApi: true };
  } catch (err) {
    log.warn(`[API] ${label} failed, using fallback`, { error: err instanceof Error ? err.message : String(err) });
    return { data: fallback, fromApi: false };
  }
}
