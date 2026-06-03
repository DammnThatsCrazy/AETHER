/**
 * KYBER API Endpoints — full coverage of the Aether backend.
 * All REST responses are wrapped in { data, status, timestamp }.
 * Each method extracts `.data` automatically unless noted.
 */
import { z } from 'zod';
import { restClient } from './rest/client';
import { log } from '@kyber/lib/logging';
import type {
  SessionsResponse, DevicesResponse, JourneysResponse, WalletsResponse,
  RelationshipsResponse, DelegationsResponse,
  UnifiedFinancialProfile, IntelligenceProfile,
  WalletRiskProfile, Web3WalletProfile, EntityCluster,
  AttributionJourney, WhyExplanation, BehavioralSignal,
  Profile360Response, EntityGraph,
} from '@aether/shared';

// ─── Response wrapper ────────────────────────────────────────────────────────
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

// ─── Common primitives ───────────────────────────────────────────────────────
const unknownSchema = z.unknown();
const listOf = (item: z.ZodType) => z.object({ data: z.array(item), total: z.number(), has_more: z.boolean().optional() });

const buildQS = (params: Record<string, string | number | boolean | undefined>) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

// ─── Shared schemas ───────────────────────────────────────────────────────────
const healthSchema = z.object({
  status: z.string(),
  uptime: z.number().optional(),
  version: z.string().optional(),
  services: z.record(z.object({ status: z.string(), latency_ms: z.number().optional(), error: z.string().optional().nullable() }).passthrough()).optional(),
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

const alertSchema = z.object({
  id: z.string().optional(),
  name: z.string(),
  condition: z.string().optional(),
  channels: z.array(z.string()).optional(),
  severity: z.string().optional(),
  active: z.boolean().optional(),
  created_at: z.string().optional(),
}).passthrough();

const webhookSchema = z.object({
  id: z.string().optional(),
  url: z.string(),
  events: z.array(z.string()),
  active: z.boolean().optional(),
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

const profileSchema = z.object({
  user_id: z.string().optional(),
  events: z.array(z.unknown()).optional(),
  connections: z.array(z.unknown()).optional(),
  timeline: z.array(z.unknown()).optional(),
  intelligence: z.record(z.unknown()).optional(),
  identifiers: z.array(z.unknown()).optional(),
}).passthrough();

// ─── API ─────────────────────────────────────────────────────────────────────
export const api = {

  // ── Analytics ──────────────────────────────────────────────────────────────
  analytics: {
    dashboardSummary: () =>
      restClient.get('/v1/analytics/dashboard/summary', wrap(z.object({
        sessions_last_24h: z.number().optional(),
        events_last_24h: z.number().optional(),
        unique_users_last_24h: z.number().optional(),
        top_events: z.array(z.object({ name: z.string(), count: z.number() })).optional(),
      }).passthrough())).then(r => r.data),

    queryEvents: (query: {
      event_type?: string;
      start_date?: string;
      end_date?: string;
      user_id?: string;
      session_id?: string;
      limit?: number;
    }) =>
      restClient.post('/v1/analytics/events/query', wrap(z.object({
        data: z.array(z.unknown()),
        pagination: z.object({ total: z.number(), limit: z.number(), has_more: z.boolean() }).optional(),
      }).passthrough()), query).then(r => r.data),

    getEvent: (eventId: string) =>
      restClient.get(`/v1/analytics/events/${eventId}`, wrap(unknownSchema)).then(r => r.data),

    graphql: (query: string, variables?: Record<string, unknown>) =>
      restClient.post('/v1/analytics/graphql', wrap(z.object({
        data: z.unknown().nullable(),
        errors: z.array(z.object({ message: z.string() }).passthrough()).optional().nullable(),
      })), { query, variables }).then(r => r.data),

    export: (params: { format?: 'csv' | 'json' | 'parquet'; start_date?: string; end_date?: string; event_type?: string }) =>
      restClient.post('/v1/analytics/export', wrap(z.object({ export_id: z.string(), status: z.string() })), params).then(r => r.data),

    exportStatus: (exportId: string) =>
      restClient.get(`/v1/analytics/export/${exportId}`, wrap(z.object({ export_id: z.string(), status: z.string(), download_url: z.string().optional() }))).then(r => r.data),

    wsUrl: (params?: { tenant_id?: string; event_type?: string }) =>
      `/v1/analytics/ws/events${buildQS({ ...params })}` as string,

    sources: () =>
      restClient.get('/v1/analytics/sources', wrap(unknownSchema)).then(r => r.data),

    getSource: (sourceId: string) =>
      restClient.get(`/v1/analytics/sources/${sourceId}`, wrap(unknownSchema)).then(r => r.data),

    channels: () =>
      restClient.get('/v1/analytics/channels', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Diagnostics ────────────────────────────────────────────────────────────
  diagnostics: {
    health: () =>
      restClient.get('/v1/diagnostics/health', wrap(healthSchema)).then(r => r.data),

    errors: (params?: { severity?: string; limit?: number; resolved?: boolean }) =>
      restClient.get(`/v1/diagnostics/errors${buildQS({ ...params })}`, wrap(z.object({
        errors: z.array(errorEntrySchema), count: z.number(),
      }))).then(r => r.data),

    report: () =>
      restClient.get('/v1/diagnostics/report', wrap(z.object({
        health: healthSchema.optional(),
        errors: z.array(errorEntrySchema).optional(),
        circuit_breakers: circuitBreakerSchema.optional(),
        services: z.record(z.unknown()).optional(),
      }).passthrough())).then(r => r.data),

    resolveError: (fingerprint: string) =>
      restClient.post(`/v1/diagnostics/errors/${fingerprint}/resolve`, wrap(z.object({ fingerprint: z.string(), resolved: z.boolean() }))),

    suppressError: (fingerprint: string) =>
      restClient.post(`/v1/diagnostics/errors/${fingerprint}/suppress`, wrap(z.object({ fingerprint: z.string(), suppressed: z.boolean() }))),

    circuitBreakers: () =>
      restClient.get('/v1/diagnostics/circuit-breakers', wrap(circuitBreakerSchema)).then(r => r.data),
  },

  // ── Intelligence ───────────────────────────────────────────────────────────
  intelligence: {
    alerts: (limit = 50) =>
      restClient.get(`/v1/intelligence/alerts?limit=${limit}`, wrap(z.object({ alerts: z.array(alertSchema), count: z.number(), queried_at: z.string().optional() }))).then(r => r.data),

    walletRisk: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/risk`, wrap(unknownSchema)).then(r => r.data as WalletRiskProfile),

    walletProfile: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/profile`, wrap(unknownSchema)).then(r => r.data as Web3WalletProfile),

    entityCluster: (entityId: string) =>
      restClient.get(`/v1/intelligence/entity/${entityId}/cluster`, wrap(unknownSchema)).then(r => r.data as EntityCluster),

    protocolAnalytics: (protocolId: string) =>
      restClient.get(`/v1/intelligence/protocol/${protocolId}/analytics`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Agent / Controllers ────────────────────────────────────────────────────
  agent: {
    status: () =>
      restClient.get('/v1/agent/status', wrap(z.object({
        active_workers: z.number().optional(),
        queued_tasks: z.number().optional(),
        completed_tasks: z.number().optional(),
        failed_tasks: z.number().optional(),
        kill_switch: z.boolean().optional(),
        workers: z.array(z.object({ worker_type: z.string(), status: z.string(), current_task: z.string().optional().nullable() }).passthrough()).optional(),
      }).passthrough())).then(r => r.data),

    getTask: (taskId: string) =>
      restClient.get(`/v1/agent/tasks/${taskId}`, wrap(taskSchema)).then(r => r.data),

    audit: (limit = 50) =>
      restClient.get(`/v1/agent/audit?limit=${limit}`, wrap(z.object({ records: z.array(z.unknown()), total: z.number() }))).then(r => r.data),

    submitTask: (workerType: string, priority: string, payload: Record<string, unknown>) =>
      restClient.post('/v1/agent/tasks', wrap(taskSchema), { worker_type: workerType, priority, payload }),

    killSwitch: (action: string) =>
      restClient.post('/v1/agent/kill-switch', wrap(z.object({ kill_switch: z.boolean(), action: z.string() })), { action }),

    agentGraph: (agentId: string, layer = 'all') =>
      restClient.get(`/v1/agent/${agentId}/graph?layer=${layer}`, wrap(unknownSchema)).then(r => r.data),

    agentTrust: (agentId: string) =>
      restClient.get(`/v1/agent/${agentId}/trust`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Profile — full + all contextual sub-resources ─────────────────────────
  profile: {
    /** Full holistic profile — identity, consent, timeline, graph, intelligence, lake data. */
    full: (userId: string, opts?: { timeline_limit?: number }) =>
      restClient.get(`/v1/profile/${userId}?include_timeline=true&include_graph=true&include_intelligence=true&include_lake=true${opts?.timeline_limit ? `&timeline_limit=${opts.timeline_limit}` : ''}`, wrap(profileSchema)).then(r => r.data),

    /** Dashboard-ready snapshot — frequency, recency, top events, loyalty tier, risk scores. */
    summary: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/summary`, wrap(unknownSchema)).then(r => r.data),

    /** Chronological event stream for the user. */
    timeline: (userId: string, params?: { limit?: number; event_type?: string }) =>
      restClient.get(`/v1/profile/${userId}/timeline${buildQS({ ...params })}`, wrap(z.object({ user_id: z.string(), events: z.array(z.unknown()), count: z.number() }))).then(r => r.data),

    /** Graph neighbourhood — identity links, ownership, delegation edges. */
    graph: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/graph`, wrap(unknownSchema)).then(r => r.data),

    /** Session rollups — device type, OS, browser, platform, geo, entry/exit URL, duration. */
    sessions: (userId: string, limit = 20) =>
      restClient.get(`/v1/profile/${userId}/sessions?limit=${limit}`, wrap(unknownSchema)).then(r => r.data as SessionsResponse),

    /** Observed devices — deterministic + probabilistic fingerprint matches. */
    devices: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/devices`, wrap(unknownSchema)).then(r => r.data as DevicesResponse),

    /** Platform distribution — web / iOS / Android / SDK / API with event counts. */
    platforms: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/platforms`, wrap(unknownSchema)).then(r => r.data),

    /** Cross-session journey chains — steps, drop-off flags, campaign linkage. */
    journeys: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/journeys`, wrap(unknownSchema)).then(r => r.data as JourneysResponse),

    /**
     * Web3 wallet profiles — for every wallet linked to the user:
     * balances by token, recent transactions, protocol interactions,
     * on-chain loyalty signals, and wallet risk scores.
     */
    wallets: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/wallets`, wrap(unknownSchema)).then(r => r.data as WalletsResponse),

    /** All identifiers — wallets, emails, device IDs, session IDs, social handles. */
    identifiers: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/identifiers`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Earned rewards, redeemed rewards, loyalty tier, points balance,
     * campaign participation history, and lifetime value (Web2 + Web3 unified).
     */
    rewards: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/rewards`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Financial profile — Web2 payments + Web3 on-chain flows unified:
     * inflows, outflows, settlements, transfers by asset, top counterparties.
     */
    financials: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/financials`, wrap(unknownSchema)).then(r => r.data as UnifiedFinancialProfile),

    /** Typed relationship edges — ownership, delegation, H2H/H2A/A2H/A2A flows. */
    relationships: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/relationships`, wrap(unknownSchema)).then(r => r.data as RelationshipsResponse),

    /** Protocol interactions derived from event stream + economic graph. */
    protocols: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/protocols`, wrap(unknownSchema)).then(r => r.data),

    /** Intelligence layer — risk scores, trust scores, anomaly scores, model features. */
    intelligence: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/intelligence`, wrap(unknownSchema)).then(r => r.data as IntelligenceProfile),

    /** Data provenance — source attribution for every data point in the profile. */
    provenance: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/provenance`, wrap(unknownSchema)).then(r => r.data),

    /** Generic deep-drill on any linked object (e.g. a specific wallet, journey, device). */
    drill: (userId: string, objectType: string, objectId: string) =>
      restClient.get(`/v1/profile/${userId}/drill/${objectType}/${objectId}`, wrap(unknownSchema)).then(r => r.data),

    /** Gold-tier data lake view for a specific domain (identity | market | onchain | social). */
    lake: (userId: string, domain: 'identity' | 'market' | 'onchain' | 'social') =>
      restClient.get(`/v1/profile/${userId}/lake/${domain}`, wrap(unknownSchema)).then(r => r.data),

    /** Aggregated social intelligence — 12 platforms with summary (total_followers_deduped, influence_level, etc.).
     *  Backend: GET /v1/profile/{id}/social-intelligence?window={window} */
    socialIntelligence: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/social-intelligence${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),

    resolve: (params: { wallet?: string; email?: string; device?: string; session?: string; social?: string; customer?: string }) =>
      restClient.get(`/v1/profile/resolve${buildQS(params)}`, wrap(z.object({ resolved_user_id: z.string() }))).then(r => r.data),
  },

  // ── Profile360 normalized surfaces ─────────────────────────────────────────
  profile360: {
    full: (entityType: string, entityId: string) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}?include=identity,system,financial,graph,timeline,analytics,debug`, wrap(unknownSchema)).then(r => r.data as Profile360Response),

    graph: (entityType: string, entityId: string, params?: { cursor?: string; limit?: number; start?: string; end?: string }) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}/graph${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    timeline: (entityType: string, entityId: string, params?: { cursor?: string; limit?: number; start?: string; end?: string; type?: string }) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}/timeline${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Identity ───────────────────────────────────────────────────────────────
  identity: {
    getProfile: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}`, wrap(profileSchema)).then(r => r.data),

    createProfile: (profile: Record<string, unknown>) =>
      restClient.post('/v1/identity/profiles', wrap(profileSchema), profile).then(r => r.data),

    updateProfile: (userId: string, updates: Record<string, unknown>) =>
      restClient.put(`/v1/identity/profiles/${userId}`, wrap(profileSchema), updates).then(r => r.data),

    mergeProfiles: (primaryId: string, secondaryId: string) =>
      restClient.post('/v1/identity/merge', wrap(unknownSchema), { primary_id: primaryId, secondary_id: secondaryId }).then(r => r.data),

    graphNeighborhood: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}/graph`, wrap(z.object({ user_id: z.string(), connections: z.array(z.unknown()) }).passthrough())).then(r => r.data),
  },

  // ── Resolution ─────────────────────────────────────────────────────────────
  resolution: {
    cluster: (userId: string) =>
      restClient.get(`/v1/resolution/cluster/${userId}`, wrap(unknownSchema)).then(r => r.data),

    pending: (limit = 50) =>
      restClient.get(`/v1/resolution/pending?limit=${limit}`, wrap(unknownSchema)).then(r => r.data),

    approve: (decisionId: string) =>
      restClient.post(`/v1/resolution/pending/${decisionId}/approve`, wrap(unknownSchema)),

    reject: (decisionId: string) =>
      restClient.post(`/v1/resolution/pending/${decisionId}/reject`, wrap(unknownSchema)),

    audit: (decisionId: string) =>
      restClient.get(`/v1/resolution/audit/${decisionId}`, wrap(unknownSchema)).then(r => r.data),

    getConfig: () =>
      restClient.get('/v1/resolution/config', wrap(unknownSchema)).then(r => r.data),

    updateConfig: (config: Record<string, unknown>) =>
      restClient.put('/v1/resolution/config', wrap(unknownSchema), config).then(r => r.data),

    runBatch: () =>
      restClient.post('/v1/resolution/batch', wrap(unknownSchema)),
  },

  // ── Entities ───────────────────────────────────────────────────────────────
  entities: {
    list: (params?: { type?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/entities${buildQS({ ...params })}`, wrap(z.object({ entities: z.array(z.unknown()), total: z.number(), has_more: z.boolean().optional() }))).then(r => r.data),

    get: (entityId: string) =>
      restClient.get(`/v1/entities/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    getGraph: (entityId: string) =>
      restClient.get(`/v1/entities/${entityId}/graph`, wrap(unknownSchema)).then(r => r.data as EntityGraph),

    search: (query: string, type?: string, limit = 20) =>
      restClient.get(`/v1/entities/search${buildQS({ q: query, type, limit })}`, wrap(z.object({ results: z.array(z.unknown()), total: z.number() }))).then(r => r.data),
  },

  // ── Notifications ──────────────────────────────────────────────────────────
  notifications: {
    listAlerts: () =>
      restClient.get('/v1/notifications/alerts', wrap(z.array(alertSchema))).then(r => r.data),

    createAlert: (alert: { name: string; condition: string; channels: string[]; recipients?: string[] }) =>
      restClient.post('/v1/notifications/alerts', wrap(alertSchema), alert),

    listWebhooks: () =>
      restClient.get('/v1/notifications/webhooks', wrap(z.array(webhookSchema))).then(r => r.data),

    createWebhook: (webhook: { url: string; events: string[]; secret?: string }) =>
      restClient.post('/v1/notifications/webhooks', wrap(webhookSchema), webhook),

    deleteWebhook: (webhookId: string) =>
      restClient.delete(`/v1/notifications/webhooks/${webhookId}`, wrap(z.object({ deleted: z.boolean() }))),
  },

  // ── Population ─────────────────────────────────────────────────────────────
  population: {
    summary: () =>
      restClient.get('/v1/population/summary', wrap(z.object({
        total_groups: z.number().optional(), total_members: z.number().optional(),
        by_type: z.record(z.number()).optional(), computed_at: z.string().optional(),
      }).passthrough())).then(r => r.data),

    groups: (type?: string, limit = 50) =>
      restClient.get(`/v1/population/groups${buildQS({ population_type: type, limit })}`, wrap(z.object({ groups: z.array(z.unknown()), count: z.number() }))).then(r => r.data),
  },

  // ── Behavioral ─────────────────────────────────────────────────────────────
  behavioral: {
    summary: () =>
      restClient.get('/v1/behavioral/summary', wrap(z.object({
        total_signals: z.number().optional(), by_family: z.record(z.number()).optional(),
        top_families: z.array(z.unknown()).optional(), computed_at: z.string().optional(),
      }).passthrough())).then(r => r.data),

    scan: (entityId: string) =>
      restClient.post(`/v1/behavioral/scan/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    entity: (entityId: string) =>
      restClient.get(`/v1/behavioral/entity/${entityId}`, wrap(unknownSchema)).then(r => r.data as { entity_id: string; signals: BehavioralSignal[] }),

    signals: (entityId: string, params?: { family?: string; limit?: number }) =>
      restClient.get(`/v1/behavioral/entity/${entityId}/signals${buildQS({ ...params })}`, wrap(z.object({ entity_id: z.string(), signals: z.array(z.unknown()), count: z.number() }))).then(r => r.data as { entity_id: string; signals: BehavioralSignal[]; count: number }),

    /** Signal registry — definitions, families, source events, outputs, consumers. */
    registry: () =>
      restClient.get('/v1/behavioral/registry', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Behavior (snapshot history) ────────────────────────────────────────────
  behavior: {
    latest: (entityId: string) =>
      restClient.get(`/v1/behavior/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    history: (entityId: string, params?: { window?: string; limit?: number }) =>
      restClient.get(`/v1/behavior/${entityId}/history${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Expectations ───────────────────────────────────────────────────────────
  expectations: {
    summary: () =>
      restClient.get('/v1/expectations/summary', wrap(unknownSchema)).then(r => r.data),

    contradictions: (limit = 50) =>
      restClient.get(`/v1/expectations/contradictions?limit=${limit}`, wrap(unknownSchema)).then(r => r.data),

    silence: () =>
      restClient.get('/v1/expectations/silence', wrap(unknownSchema)).then(r => r.data),

    group: (populationId: string) =>
      restClient.get(`/v1/expectations/group/${populationId}`, wrap(unknownSchema)).then(r => r.data),

    groupGaps: (populationId: string) =>
      restClient.get(`/v1/expectations/group/${populationId}/gaps`, wrap(unknownSchema)).then(r => r.data),

    entity: (entityId: string) =>
      restClient.get(`/v1/expectations/entity/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    entitySignals: (entityId: string, params?: { signal_type?: string; limit?: number }) =>
      restClient.get(`/v1/expectations/entity/${entityId}/signals${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    explain: (entityId: string) =>
      restClient.get(`/v1/expectations/entity/${entityId}/explain`, wrap(unknownSchema)).then(r => r.data as WhyExplanation),

    scan: (entityId: string) =>
      restClient.post(`/v1/expectations/scan/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    getSignal: (signalId: string) =>
      restClient.get(`/v1/expectations/signal/${signalId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Automation ─────────────────────────────────────────────────────────────
  automation: {
    ingest: (event: { type: string; campaign_id?: string; user?: Record<string, unknown>; wallet_address?: string; timestamp?: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/automation/ingest', wrap(unknownSchema), event).then(r => r.data),

    metrics: (campaignId: string, hours = 24) =>
      restClient.get(`/v1/automation/metrics/${campaignId}?hours=${hours}`, wrap(unknownSchema)).then(r => r.data),

    overview: (hours = 24) =>
      restClient.get(`/v1/automation/overview?hours=${hours}`, wrap(unknownSchema)).then(r => r.data),

    insights: () =>
      restClient.get('/v1/automation/insights', wrap(unknownSchema)).then(r => r.data),

    report: (campaignId: string) =>
      restClient.post(`/v1/automation/report/${campaignId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Campaigns ──────────────────────────────────────────────────────────────
  campaigns: {
    list: (params?: { status?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/campaigns${buildQS({ ...params })}`, wrap(z.object({ campaigns: z.array(z.unknown()), total: z.number() }))).then(r => r.data),

    get: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}`, wrap(unknownSchema)).then(r => r.data),

    create: (campaign: Record<string, unknown>) =>
      restClient.post('/v1/campaigns', wrap(unknownSchema), campaign).then(r => r.data),

    update: (campaignId: string, updates: Record<string, unknown>) =>
      restClient.patch(`/v1/campaigns/${campaignId}`, wrap(unknownSchema), updates).then(r => r.data),

    delete: (campaignId: string) =>
      restClient.delete(`/v1/campaigns/${campaignId}`, wrap(z.object({ deleted: z.boolean() }))),

    touchpoint: (campaignId: string, tp: { channel?: string; source?: string; user_id?: string; session_id?: string; event_type?: string; is_conversion?: boolean; revenue_usd?: number; timestamp?: string; properties?: Record<string, unknown> }) =>
      restClient.post(`/v1/campaigns/${campaignId}/touchpoints`, wrap(unknownSchema), tp).then(r => r.data),

    /** Multi-touch attribution — models: multi_touch | first_touch | last_touch | linear | time_decay */
    attribution: (campaignId: string, params?: { model?: string; start_date?: string; end_date?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/attribution${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Attribution ────────────────────────────────────────────────────────────
  attribution: {
    resolve: (params: { user_id: string; event: Record<string, unknown>; model?: string; touchpoints?: unknown[] }) =>
      restClient.post('/v1/attribution/resolve', wrap(unknownSchema), params).then(r => r.data),

    recordTouchpoint: (touchpoint: { user_id: string; channel: string; source: string; campaign?: string; event_type: string; timestamp: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/attribution/touchpoints', wrap(unknownSchema), touchpoint).then(r => r.data),

    journey: (userId: string) =>
      restClient.get(`/v1/attribution/journey/${userId}`, wrap(unknownSchema)).then(r => r.data as AttributionJourney),

    clearJourney: (userId: string) =>
      restClient.delete(`/v1/attribution/journey/${userId}`, wrap(unknownSchema)),

    models: () =>
      restClient.get('/v1/attribution/models', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Consent ────────────────────────────────────────────────────────────────
  consent: {
    getProfile: (userId: string) =>
      restClient.get(`/v1/consent/${userId}`, wrap(z.object({
        user_id: z.string(),
        purposes: z.record(z.boolean()),
        updated_at: z.string().optional(),
        version: z.string().optional(),
      }).passthrough())).then(r => r.data),

    update: (userId: string, purposes: Record<string, boolean>) =>
      restClient.post(`/v1/consent/${userId}`, wrap(unknownSchema), { purposes }),

    listDsrRequests: (params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/consent/dsr${buildQS({ ...params })}`, wrap(z.object({ requests: z.array(z.unknown()), count: z.number() }))).then(r => r.data),

    getDsrRequest: (requestId: string) =>
      restClient.get(`/v1/consent/dsr/${requestId}`, wrap(unknownSchema)).then(r => r.data),

    completeDsr: (requestId: string, notes?: string) =>
      restClient.post(`/v1/consent/dsr/${requestId}/complete`, wrap(unknownSchema), { notes }),
  },

  // ── Rewards ────────────────────────────────────────────────────────────────
  rewards: {
    evaluate: (event: { event_type: string; user_address: string; channel?: string; session_id?: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/rewards/evaluate', wrap(unknownSchema), event).then(r => r.data),

    listCampaigns: (params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/rewards/campaigns${buildQS({ ...params })}`, wrap(z.object({ campaigns: z.array(z.unknown()), count: z.number() }))).then(r => r.data),

    getCampaign: (campaignId: string) =>
      restClient.get(`/v1/rewards/campaigns/${campaignId}`, wrap(unknownSchema)).then(r => r.data),

    createCampaign: (campaign: Record<string, unknown>) =>
      restClient.post('/v1/rewards/campaigns', wrap(unknownSchema), campaign).then(r => r.data),

    queueStats: () =>
      restClient.get('/v1/rewards/queue/stats', wrap(unknownSchema)).then(r => r.data),

    userRewards: (address: string) =>
      restClient.get(`/v1/rewards/user/${address}`, wrap(unknownSchema)).then(r => r.data),

    processQueue: () =>
      restClient.post('/v1/rewards/process', wrap(unknownSchema)).then(r => r.data),

    getProof: (rewardId: string) =>
      restClient.get(`/v1/rewards/proof/${rewardId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Oracle (proof generation / verification) ───────────────────────────────
  oracle: {
    generateProof: (params: { entity_id: string; data_type: string; chain: string }) =>
      restClient.post('/v1/oracle/proof', wrap(z.object({
        proof_id: z.string(), proof: z.string(), chain: z.string(), expires_at: z.string().optional(),
      }).passthrough()), params).then(r => r.data),

    verifyProof: (proofId: string, proof: string) =>
      restClient.post('/v1/oracle/verify', wrap(z.object({
        verified: z.boolean(), proof_id: z.string(), verified_at: z.string().optional(),
      }).passthrough()), { proof_id: proofId, proof }).then(r => r.data),

    getStatus: (proofId: string) =>
      restClient.get(`/v1/oracle/proof/${proofId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Scoring (via ML serving) ────────────────────────────────────────────────
  scoring: {
    entityScore: (entityId: string, features?: Record<string, unknown>) =>
      restClient.post('/v1/ml/predict', wrap(unknownSchema), { model_name: 'trust_scoring', entity_id: entityId, features: features ?? {}, use_cache: true }).then(r => r.data),

    walletScore: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/risk`, wrap(unknownSchema)).then(r => r.data),

    batch: (entityIds: readonly string[]) =>
      restClient.post('/v1/ml/predict/batch', wrap(z.object({ scores: z.array(z.unknown()), computed_at: z.string() })), { model_name: 'trust_scoring', entities: entityIds.map(id => ({ entity_id: id, features: {}, use_cache: true })) }).then(r => r.data),

    features: (entityId: string) =>
      restClient.get(`/v1/ml/features/${entityId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── ML Serving ─────────────────────────────────────────────────────────────
  ml: {
    models: () =>
      restClient.get('/v1/ml/models', wrap(z.object({ models: z.array(unknownSchema) }))).then(r => r.data.models),

    predict: (modelName: string, entityId: string, features?: Record<string, unknown>, useCache = true) =>
      restClient.post('/v1/ml/predict', wrap(unknownSchema), { model_name: modelName, entity_id: entityId, features: features ?? {}, use_cache: useCache }).then(r => r.data),

    predictBatch: (modelName: string, entities: Array<{ entity_id: string; features?: Record<string, unknown> }>) =>
      restClient.post('/v1/ml/predict/batch', wrap(unknownSchema), { model_name: modelName, entities }).then(r => r.data),

    features: (entityId: string) =>
      restClient.get(`/v1/ml/features/${entityId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Fraud ──────────────────────────────────────────────────────────────────
  fraud: {
    evaluate: (event: Record<string, unknown>, context?: Record<string, unknown>) =>
      restClient.post('/v1/fraud/evaluate', wrap(unknownSchema), { event, context }).then(r => r.data),

    evaluateBatch: (events: unknown[]) =>
      restClient.post('/v1/fraud/evaluate/batch', wrap(unknownSchema), { events }).then(r => r.data),

    getConfig: () =>
      restClient.get('/v1/fraud/config', wrap(unknownSchema)).then(r => r.data),

    updateConfig: (config: Record<string, unknown>) =>
      restClient.put('/v1/fraud/config', wrap(unknownSchema), config).then(r => r.data),

    stats: () =>
      restClient.get('/v1/fraud/stats', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Traffic ────────────────────────────────────────────────────────────────
  traffic: {
    reportSource: (source: { session_id: string; source: string; timestamp: string; [k: string]: unknown }) =>
      restClient.post('/v1/track/traffic-source', wrap(unknownSchema), source).then(r => r.data),

    trackEvent: (event: { type: string; session_id: string; timestamp: string; data?: Record<string, unknown> }) =>
      restClient.post('/v1/track/events', wrap(unknownSchema), event).then(r => r.data),
  },

  // ── Delegation ─────────────────────────────────────────────────────────────
  delegation: {
    grant: (delegation: { grantor_entity_id: string; grantee_entity_id: string; scope: string[]; starts_at?: string; ends_at?: string }) =>
      restClient.post('/v1/delegations', wrap(unknownSchema), delegation).then(r => r.data),

    get: (delegationId: string) =>
      restClient.get(`/v1/delegations/${delegationId}`, wrap(unknownSchema)).then(r => r.data),

    revoke: (delegationId: string) =>
      restClient.post(`/v1/delegations/${delegationId}/revoke`, wrap(unknownSchema)).then(r => r.data),

    list: (params?: { grantor?: string; grantee?: string; active?: boolean; limit?: number }) =>
      restClient.get(`/v1/delegations${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data as DelegationsResponse),

    validate: (params: { grantee_entity_id: string; action: string; resource: string; amount?: number }) =>
      restClient.post('/v1/delegations/validate', wrap(unknownSchema), params).then(r => r.data),
  },

  // ── Providers (BYOK) ───────────────────────────────────────────────────────
  providers: {
    storeKey: (key: { provider_name: string; api_key: string; endpoint?: string }) =>
      restClient.post('/v1/providers/keys', wrap(unknownSchema), key).then(r => r.data),

    listKeys: () =>
      restClient.get('/v1/providers/keys', wrap(z.array(unknownSchema))).then(r => r.data),

    deleteKey: (provider: string) =>
      restClient.delete(`/v1/providers/keys/${provider}`, wrap(unknownSchema)),

    usage: (params?: { category?: string; provider_name?: string }) =>
      restClient.get(`/v1/providers/usage${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    usageSummary: () =>
      restClient.get('/v1/providers/usage/summary', wrap(unknownSchema)).then(r => r.data),

    health: () =>
      restClient.get('/v1/providers/health', wrap(unknownSchema)).then(r => r.data),

    categories: () =>
      restClient.get('/v1/providers/categories', wrap(unknownSchema)).then(r => r.data),

    test: (params: { category: string; method: string; params: Record<string, unknown>; preferred_provider?: string }) =>
      restClient.post('/v1/providers/test', wrap(unknownSchema), params).then(r => r.data),
  },

  // ── Realtime (returns URLs for EventSource / WebSocket) ────────────────────
  realtime: {
    sseUrl: (entityId?: string) => `/v1/realtime/sse${entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ''}`,
    wsUrl: (entityId?: string) => `/v1/realtime/ws${entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ''}`,
  },

  // ── Ingestion ──────────────────────────────────────────────────────────────
  ingest: {
    event: (event: { event_type: string; session_id: string; properties?: Record<string, unknown>; timestamp?: string; user_id?: string; device_id?: string }) =>
      restClient.post('/v1/ingest/events', wrap(unknownSchema), event).then(r => r.data),

    batch: (events: unknown[]) =>
      restClient.post('/v1/ingest/events/batch', wrap(unknownSchema), { events }).then(r => r.data),

    feed: (feed: { source: string; entity_type: string; data: Record<string, unknown> }) =>
      restClient.post('/v1/ingest/feed', wrap(unknownSchema), feed).then(r => r.data),
  },

  // ── Web3 ───────────────────────────────────────────────────────────────────
  web3: {
    chains: {
      list: (params?: { vm_family?: string; limit?: number }) =>
        restClient.get(`/v1/web3/chains${buildQS({ ...params })}`, wrap(z.object({ chains: z.array(unknownSchema), count: z.number() }))).then(r => r.data.chains),
      get: (chainId: string) =>
        restClient.get(`/v1/web3/chains/${chainId}`, wrap(unknownSchema)).then(r => r.data),
      register: (chain: Record<string, unknown>) =>
        restClient.post('/v1/web3/chains', wrap(unknownSchema), chain).then(r => r.data),
    },
    protocols: {
      list: (params?: { family?: string; chain?: string; q?: string; limit?: number }) =>
        restClient.get(`/v1/web3/protocols${buildQS({ ...params })}`, wrap(z.object({ protocols: z.array(unknownSchema), count: z.number() }))).then(r => r.data.protocols),
      get: (protocolId: string) =>
        restClient.get(`/v1/web3/protocols/${protocolId}`, wrap(unknownSchema)).then(r => r.data),
      register: (protocol: Record<string, unknown>) =>
        restClient.post('/v1/web3/protocols', wrap(unknownSchema), protocol).then(r => r.data),
    },
    contracts: {
      get: (chainId: string, address: string) =>
        restClient.get(`/v1/web3/contracts/${chainId}/${address}`, wrap(unknownSchema)).then(r => r.data),
      unclassified: (params?: { chain_id?: string; limit?: number }) =>
        restClient.get(`/v1/web3/contracts/unclassified${buildQS({ ...params })}`, wrap(z.object({ contracts: z.array(unknownSchema), count: z.number() }))).then(r => r.data.contracts),
      register: (contract: Record<string, unknown>) =>
        restClient.post('/v1/web3/contracts', wrap(unknownSchema), contract).then(r => r.data),
      reclassify: (chainId: string, address: string, body: Record<string, unknown>) =>
        restClient.post(`/v1/web3/contracts/${chainId}/${address}/reclassify`, wrap(unknownSchema), body).then(r => r.data),
    },
    tokens: {
      list: (params?: { chain_id?: string; stablecoins?: boolean; limit?: number }) =>
        restClient.get(`/v1/web3/tokens${buildQS({ ...params })}`, wrap(z.object({ tokens: z.array(unknownSchema), count: z.number() }))).then(r => r.data.tokens),
      register: (token: Record<string, unknown>) =>
        restClient.post('/v1/web3/tokens', wrap(unknownSchema), token).then(r => r.data),
    },
    apps: {
      list: (limit = 50) =>
        restClient.get(`/v1/web3/apps?limit=${limit}`, wrap(z.object({ apps: z.array(unknownSchema), count: z.number() }))).then(r => r.data.apps),
      register: (app: Record<string, unknown>) =>
        restClient.post('/v1/web3/apps', wrap(unknownSchema), app).then(r => r.data),
    },
    domains: {
      get: (domain: string) =>
        restClient.get(`/v1/web3/domains/${encodeURIComponent(domain)}`, wrap(unknownSchema)).then(r => r.data),
      register: (domain: Record<string, unknown>) =>
        restClient.post('/v1/web3/domains', wrap(unknownSchema), domain).then(r => r.data),
    },
    governance: {
      listSpaces: (params?: { protocol_id?: string; limit?: number }) =>
        restClient.get(`/v1/web3/governance/spaces${buildQS({ ...params })}`, wrap(z.object({ spaces: z.array(unknownSchema), count: z.number() }))).then(r => r.data.spaces),
      registerSpace: (space: Record<string, unknown>) =>
        restClient.post('/v1/web3/governance/spaces', wrap(unknownSchema), space).then(r => r.data),
    },
    classify: {
      contract: (chainId: string, address: string) =>
        restClient.post('/v1/web3/classify/contract', wrap(unknownSchema), { chain_id: chainId, address }).then(r => r.data),
      method: (selector: string) =>
        restClient.post('/v1/web3/classify/method', wrap(unknownSchema), { selector }).then(r => r.data),
      domain: (domain: string) =>
        restClient.post('/v1/web3/classify/domain', wrap(unknownSchema), { domain }).then(r => r.data),
      observation: (observation: Record<string, unknown>, buildGraph = false) =>
        restClient.post('/v1/web3/classify/observation', wrap(unknownSchema), { ...observation, build_graph: buildGraph }).then(r => r.data),
    },
    observations: {
      batch: (observations: unknown[], buildGraph = false, source?: string, sourceTag?: string) =>
        restClient.post('/v1/web3/observations/batch', wrap(unknownSchema), { observations, build_graph: buildGraph, source, source_tag: sourceTag }).then(r => r.data),
    },
    migrations: {
      list: (protocolId: string, limit = 50) =>
        restClient.get(`/v1/web3/migrations/${protocolId}?limit=${limit}`, wrap(z.object({ protocol_id: z.string(), migrations: z.array(unknownSchema), count: z.number() }))).then(r => r.data.migrations),
      record: (migration: Record<string, unknown>) =>
        restClient.post('/v1/web3/migrations', wrap(unknownSchema), migration).then(r => r.data),
      detect: (protocolId: string, address: string, chainId: string) =>
        restClient.post('/v1/web3/migrations/detect', wrap(unknownSchema), { protocol_id: protocolId, address, chain_id: chainId }).then(r => r.data),
    },
    coverage: {
      status: () =>
        restClient.get('/v1/web3/coverage/status', wrap(unknownSchema)).then(r => r.data),
      health: () =>
        restClient.get('/v1/web3/coverage/health', wrap(unknownSchema)).then(r => r.data),
    },
  },

  // ── On-Chain ───────────────────────────────────────────────────────────────
  onchain: {
    recordAction: (action: Record<string, unknown>) =>
      restClient.post('/v1/onchain/actions', wrap(unknownSchema), action).then(r => r.data),

    agentActions: (agentId: string) =>
      restClient.get(`/v1/onchain/actions/${agentId}`, wrap(z.object({ agent_id: z.string(), actions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.actions),

    getContract: (address: string) =>
      restClient.get(`/v1/onchain/contracts/${address}`, wrap(unknownSchema)).then(r => r.data),

    configureListener: (config: Record<string, unknown>) =>
      restClient.post('/v1/onchain/listener/configure', wrap(unknownSchema), config).then(r => r.data),

    rpcHealth: () =>
      restClient.get('/v1/onchain/rpc/health', wrap(unknownSchema)).then(r => r.data),
  },

  // ── x402 (HTTP Payment Tracking) ──────────────────────────────────────────
  x402: {
    capture: (transaction: Record<string, unknown>) =>
      restClient.post('/v1/x402/capture', wrap(unknownSchema), transaction).then(r => r.data),

    graph: () =>
      restClient.get('/v1/x402/graph', wrap(unknownSchema)).then(r => r.data),

    agentHistory: (agentId: string) =>
      restClient.get(`/v1/x402/agent/${agentId}`, wrap(unknownSchema)).then(r => r.data),

    snapshotGraph: () =>
      restClient.post('/v1/x402/graph/snapshot', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Flows (transfers / wallets / assets) ───────────────────────────────────
  flows: {
    transfers: {
      record: (transfer: { from_entity_id: string; to_entity_id: string; asset_id: string; amount: number; [k: string]: unknown }) =>
        restClient.post('/v1/flows/transfers', wrap(unknownSchema), transfer).then(r => r.data),
      list: (entityId: string, limit = 50) =>
        restClient.get(`/v1/flows/transfers${buildQS({ entity_id: entityId, limit })}`, wrap(z.object({ entity_id: z.string(), transfers: z.array(unknownSchema), count: z.number() }))).then(r => r.data.transfers),
    },
    wallets: {
      link: (wallet: { owner_entity_id: string; chain: string; address: string }) =>
        restClient.post('/v1/flows/wallets', wrap(unknownSchema), wallet).then(r => r.data),
      list: (entityId: string, limit = 50) =>
        restClient.get(`/v1/flows/wallets${buildQS({ entity_id: entityId, limit })}`, wrap(z.object({ entity_id: z.string(), wallets: z.array(unknownSchema), count: z.number() }))).then(r => r.data.wallets),
    },
    assets: {
      register: (asset: { asset_type: string; chain: string; symbol: string; [k: string]: unknown }) =>
        restClient.post('/v1/flows/assets', wrap(unknownSchema), asset).then(r => r.data),
      get: (assetId: string) =>
        restClient.get(`/v1/flows/assets/${assetId}`, wrap(unknownSchema)).then(r => r.data),
    },
  },

  // ── RWA (Real-World Assets) ────────────────────────────────────────────────
  rwa: {
    assets: {
      list: (params?: { asset_class?: string; chain?: string; limit?: number }) =>
        restClient.get(`/v1/rwa/assets${buildQS({ ...params })}`, wrap(z.object({ assets: z.array(unknownSchema), count: z.number() }))).then(r => r.data.assets),
      get: (assetId: string) =>
        restClient.get(`/v1/rwa/assets/${assetId}`, wrap(unknownSchema)).then(r => r.data),
      create: (asset: Record<string, unknown>) =>
        restClient.post('/v1/rwa/assets', wrap(unknownSchema), asset).then(r => r.data),
      holders: (assetId: string, limit = 50) =>
        restClient.get(`/v1/rwa/assets/${assetId}/holders?limit=${limit}`, wrap(z.object({ asset_id: z.string(), holders: z.array(unknownSchema), count: z.number() }))).then(r => r.data.holders),
      cashflows: (assetId: string, params?: { cashflow_type?: string; limit?: number }) =>
        restClient.get(`/v1/rwa/assets/${assetId}/cashflows${buildQS({ ...params })}`, wrap(z.object({ asset_id: z.string(), cashflows: z.array(unknownSchema), count: z.number() }))).then(r => r.data.cashflows),
      reserveCredibility: (assetId: string) =>
        restClient.get(`/v1/rwa/assets/${assetId}/reserve-credibility`, wrap(unknownSchema)).then(r => r.data),
      redemptionPressure: (assetId: string) =>
        restClient.get(`/v1/rwa/assets/${assetId}/redemption-pressure`, wrap(unknownSchema)).then(r => r.data),
    },
    policies: {
      create: (policy: Record<string, unknown>) =>
        restClient.post('/v1/rwa/policies', wrap(unknownSchema), policy).then(r => r.data),
      forAsset: (assetId: string) =>
        restClient.get(`/v1/rwa/assets/${assetId}/policies`, wrap(z.object({ asset_id: z.string(), policies: z.array(unknownSchema), count: z.number() }))).then(r => r.data.policies),
    },
    simulateTransfer: (params: { asset_id: string; from_entity: string; to_entity: string; amount: number }) =>
      restClient.post('/v1/rwa/simulate-transfer', wrap(unknownSchema), params).then(r => r.data),
    recordCashflow: (cashflow: Record<string, unknown>) =>
      restClient.post('/v1/rwa/cashflows', wrap(unknownSchema), cashflow).then(r => r.data),
    exposure: (entityId: string, params?: { entity_type?: string; include_inferred?: boolean; include_beneficial?: boolean }) =>
      restClient.get(`/v1/rwa/exposure/${entityId}${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
    registerHolder: (holder: Record<string, unknown>) =>
      restClient.post('/v1/rwa/holders', wrap(unknownSchema), holder).then(r => r.data),
  },

  // ── Cross-Domain ───────────────────────────────────────────────────────────
  crossdomain: {
    institutions: {
      list: (params?: { institution_type?: string; q?: string; limit?: number }) =>
        restClient.get(`/v1/crossdomain/institutions${buildQS({ ...params })}`, wrap(z.object({ institutions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.institutions),
      get: (id: string) =>
        restClient.get(`/v1/crossdomain/institutions/${id}`, wrap(unknownSchema)).then(r => r.data),
      register: (institution: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/institutions', wrap(unknownSchema), institution).then(r => r.data),
    },
    accounts: {
      list: (params?: { owner?: string; institution?: string; account_type?: string; limit?: number }) =>
        restClient.get(`/v1/crossdomain/accounts${buildQS({ ...params })}`, wrap(z.object({ accounts: z.array(unknownSchema), count: z.number() }))).then(r => r.data.accounts),
      get: (id: string) =>
        restClient.get(`/v1/crossdomain/accounts/${id}`, wrap(unknownSchema)).then(r => r.data),
      positions: (id: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/accounts/${id}/positions?limit=${limit}`, wrap(z.object({ account_id: z.string(), positions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.positions),
      register: (account: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/accounts', wrap(unknownSchema), account).then(r => r.data),
    },
    instruments: {
      list: (params?: { instrument_type?: string; issuer?: string; q?: string; limit?: number }) =>
        restClient.get(`/v1/crossdomain/instruments${buildQS({ ...params })}`, wrap(z.object({ instruments: z.array(unknownSchema), count: z.number() }))).then(r => r.data.instruments),
      get: (id: string) =>
        restClient.get(`/v1/crossdomain/instruments/${id}`, wrap(unknownSchema)).then(r => r.data),
      bySymbol: (symbol: string) =>
        restClient.get(`/v1/crossdomain/instruments/symbol/${encodeURIComponent(symbol)}`, wrap(unknownSchema)).then(r => r.data),
      register: (instrument: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/instruments', wrap(unknownSchema), instrument).then(r => r.data),
    },
    orders: {
      list: (accountId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/orders/${accountId}?limit=${limit}`, wrap(z.object({ account_id: z.string(), orders: z.array(unknownSchema), count: z.number() }))).then(r => r.data.orders),
      record: (order: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/orders', wrap(unknownSchema), order).then(r => r.data),
    },
    executions: {
      byOrder: (orderId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/executions/order/${orderId}?limit=${limit}`, wrap(z.object({ order_id: z.string(), executions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.executions),
      byAccount: (accountId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/executions/account/${accountId}?limit=${limit}`, wrap(z.object({ account_id: z.string(), executions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.executions),
      record: (execution: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/executions', wrap(unknownSchema), execution).then(r => r.data),
    },
    balances: {
      latest: (accountId: string) =>
        restClient.get(`/v1/crossdomain/balances/${accountId}/latest`, wrap(unknownSchema)).then(r => r.data),
      record: (balance: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/balances', wrap(unknownSchema), balance).then(r => r.data),
    },
    cashMovements: {
      list: (accountId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/cash-movements/${accountId}?limit=${limit}`, wrap(z.object({ account_id: z.string(), movements: z.array(unknownSchema), count: z.number() }))).then(r => r.data.movements),
      record: (movement: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/cash-movements', wrap(unknownSchema), movement).then(r => r.data),
    },
    compliance: {
      listActions: (entityId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/compliance/actions/${entityId}?limit=${limit}`, wrap(z.object({ entity_id: z.string(), actions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.actions),
      recordAction: (action: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/compliance/actions', wrap(unknownSchema), action).then(r => r.data),
    },
    events: {
      byEntity: (entityId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/events/entity/${entityId}?limit=${limit}`, wrap(z.object({ entity_id: z.string(), events: z.array(unknownSchema), count: z.number() }))).then(r => r.data.events),
      byInstrument: (instrumentId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/events/instrument/${instrumentId}?limit=${limit}`, wrap(z.object({ instrument_id: z.string(), events: z.array(unknownSchema), count: z.number() }))).then(r => r.data.events),
      record: (event: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/events', wrap(unknownSchema), event).then(r => r.data),
    },
    links: {
      list: (entityId: string, limit = 50) =>
        restClient.get(`/v1/crossdomain/links/${entityId}?limit=${limit}`, wrap(z.object({ entity_id: z.string(), links: z.array(unknownSchema), count: z.number() }))).then(r => r.data.links),
      highConfidence: (params?: { min_confidence?: number; limit?: number }) =>
        restClient.get(`/v1/crossdomain/links/high-confidence${buildQS({ ...params })}`, wrap(z.object({ links: z.array(unknownSchema), count: z.number(), min_confidence: z.number() }))).then(r => r.data.links),
      create: (link: Record<string, unknown>) =>
        restClient.post('/v1/crossdomain/links', wrap(unknownSchema), link).then(r => r.data),
    },
    fusion: {
      exposure: (entityId: string) =>
        restClient.get(`/v1/crossdomain/fusion/exposure/${entityId}`, wrap(unknownSchema)).then(r => r.data),
      profile: (entityId: string) =>
        restClient.get(`/v1/crossdomain/fusion/profile/${entityId}`, wrap(unknownSchema)).then(r => r.data),
    },
    coverage: {
      status: () => restClient.get('/v1/crossdomain/coverage/status', wrap(unknownSchema)).then(r => r.data),
      health: () => restClient.get('/v1/crossdomain/coverage/health', wrap(unknownSchema)).then(r => r.data),
    },
  },

  // ── Lake (data lake) ───────────────────────────────────────────────────────
  lake: {
    ingest: (params: { domain: string; source: string; source_tag: string; records: unknown[] }) =>
      restClient.post('/v1/lake/ingest', wrap(unknownSchema), params).then(r => r.data),

    rollback: (params: { domain: string; source_tag: string; tiers?: string[] }) =>
      restClient.post('/v1/lake/rollback', wrap(unknownSchema), params).then(r => r.data),

    audit: (domain: string, sourceTag: string) =>
      restClient.get(`/v1/lake/audit/${domain}/${encodeURIComponent(sourceTag)}`, wrap(unknownSchema)).then(r => r.data),

    materialize: (params: { domain: string; entity_id: string; metric: string; value: unknown; [k: string]: unknown }) =>
      restClient.post('/v1/lake/materialize', wrap(unknownSchema), params).then(r => r.data),

    gold: (domain: string, entityId: string) =>
      restClient.get(`/v1/lake/gold/${domain}/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    quality: (domain: string) =>
      restClient.get(`/v1/lake/quality/${domain}`, wrap(unknownSchema)).then(r => r.data),

    status: () =>
      restClient.get('/v1/lake/status', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Admin (tenant / billing) ───────────────────────────────────────────────
  admin: {
    tenants: {
      list: (params?: { limit?: number; offset?: number; plan?: string; status?: string }) =>
        restClient.get(`/v1/admin/tenants${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data as { tenants: unknown[]; total: number }),
      create: (tenant: { name: string; plan: string; contact_email: string; settings?: Record<string, unknown> }) =>
        restClient.post('/v1/admin/tenants', wrap(unknownSchema), tenant).then(r => r.data),
      get: (tenantId: string) =>
        restClient.get(`/v1/admin/tenants/${tenantId}`, wrap(unknownSchema)).then(r => r.data),
      update: (tenantId: string, updates: Record<string, unknown>) =>
        restClient.patch(`/v1/admin/tenants/${tenantId}`, wrap(unknownSchema), updates).then(r => r.data),
      deactivate: (tenantId: string) =>
        restClient.post(`/v1/admin/tenants/${tenantId}/deactivate`, wrap(unknownSchema), {}).then(r => r.data),
      delete: (tenantId: string) =>
        restClient.delete(`/v1/admin/tenants/${tenantId}`, wrap(unknownSchema)).then(r => r.data),
    },
    apiKeys: {
      create: (tenantId: string, key: { name: string; scopes?: string[] }) =>
        restClient.post(`/v1/admin/tenants/${tenantId}/api-keys`, wrap(unknownSchema), key).then(r => r.data),
      list: (tenantId: string) =>
        restClient.get(`/v1/admin/tenants/${tenantId}/api-keys`, wrap(z.array(unknownSchema))).then(r => r.data),
      revoke: (keyId: string) =>
        restClient.delete(`/v1/admin/api-keys/${keyId}`, wrap(z.object({ revoked: z.boolean() }))),
    },
    billing: {
      info: (tenantId: string) =>
        restClient.get(`/v1/admin/tenants/${tenantId}/billing`, wrap(unknownSchema)).then(r => r.data),
      usage: (tenantId: string) =>
        restClient.get(`/v1/admin/tenants/${tenantId}/billing/usage`, wrap(unknownSchema)).then(r => r.data),
      invoices: (tenantId: string, limit = 10) =>
        restClient.get(`/v1/admin/tenants/${tenantId}/billing/invoices?limit=${limit}`, wrap(z.object({ tenant_id: z.string(), invoices: z.array(unknownSchema), count: z.number() }))).then(r => r.data.invoices),
      getInvoice: (tenantId: string, invoiceId: string) =>
        restClient.get(`/v1/admin/tenants/${tenantId}/billing/invoices/${invoiceId}`, wrap(unknownSchema)).then(r => r.data),
      createCheckoutSession: (tenantId: string, params: Record<string, unknown>) =>
        restClient.post(`/v1/admin/tenants/${tenantId}/billing/checkout-session`, wrap(unknownSchema), params).then(r => r.data),
      createPortalSession: (tenantId: string) =>
        restClient.post(`/v1/admin/tenants/${tenantId}/billing/portal-session`, wrap(unknownSchema)).then(r => r.data),
      createOverageInvoice: (tenantId: string, params: Record<string, unknown>) =>
        restClient.post(`/v1/admin/tenants/${tenantId}/billing/overage-invoice`, wrap(unknownSchema), params).then(r => r.data),
    },
    kyber: {
      strategicOverview: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/strategic-overview${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      tenantValueHealth: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/tenant-value-health${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      tenantExpansionOpportunities: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/tenant-expansion-opportunities${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      tenantChurnRisk: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/tenant-churn-risk${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      recommendationFamilyPerformance: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/recommendation-family-performance${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      playbookPerformance: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/playbook-performance${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      outcomeCaptureHealth: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/outcome-capture-health${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      modelConfidenceDrift: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/model-confidence-drift${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      verticalSolutionSignals: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/vertical-solution-signals${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      revenueOpportunities: (window = '30d') =>
        restClient.get(`/v1/admin/kyber/revenue-opportunities${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
      solutionPackages: () =>
        restClient.get('/v1/admin/kyber/solution-packages', wrap(unknownSchema)).then(r => r.data),
      solutionPackage: (packageId: string) =>
        restClient.get(`/v1/admin/kyber/solution-packages/${packageId}`, wrap(unknownSchema)).then(r => r.data),
      packageReadiness: () =>
        restClient.get('/v1/admin/kyber/package-readiness', wrap(unknownSchema)).then(r => r.data),
      deploymentModes: () =>
        restClient.get('/v1/admin/kyber/deployment-modes', wrap(unknownSchema)).then(r => r.data),
      deploymentReadiness: () =>
        restClient.get('/v1/admin/kyber/deployment-readiness', wrap(unknownSchema)).then(r => r.data),
      revopsOverview: () =>
        restClient.get('/v1/admin/kyber/revops/overview', wrap(unknownSchema)).then(r => r.data),
      revopsContracts: () =>
        restClient.get('/v1/admin/kyber/revops/contracts', wrap(unknownSchema)).then(r => r.data),
      revopsUsage: () =>
        restClient.get('/v1/admin/kyber/revops/usage', wrap(unknownSchema)).then(r => r.data),
      revopsInvoicePreviews: () =>
        restClient.get('/v1/admin/kyber/revops/invoice-previews', wrap(unknownSchema)).then(r => r.data),
      revopsValueCreated: () =>
        restClient.get('/v1/admin/kyber/revops/value-created', wrap(unknownSchema)).then(r => r.data),
      revopsRevenueLeakage: () =>
        restClient.get('/v1/admin/kyber/revops/revenue-leakage', wrap(unknownSchema)).then(r => r.data),
      revopsExpansionBillingOpportunities: () =>
        restClient.get('/v1/admin/kyber/revops/expansion-billing-opportunities', wrap(unknownSchema)).then(r => r.data),
      auditExportHealth: () =>
        restClient.get('/v1/admin/kyber/audit-export-health', wrap(unknownSchema)).then(r => r.data),
      gtmMaterials: () =>
        restClient.get('/v1/admin/kyber/gtm/materials', wrap(unknownSchema)).then(r => r.data),
      gtmMaterial: (materialId: string) =>
        restClient.get(`/v1/admin/kyber/gtm/materials/${materialId}`, wrap(unknownSchema)).then(r => r.data),
      buyerPersonas: () =>
        restClient.get('/v1/admin/kyber/gtm/buyer-personas', wrap(unknownSchema)).then(r => r.data),
      pricingModels: () =>
        restClient.get('/v1/admin/kyber/gtm/pricing-models', wrap(unknownSchema)).then(r => r.data),
      roiCalculators: () =>
        restClient.get('/v1/admin/kyber/gtm/roi-calculators', wrap(unknownSchema)).then(r => r.data),
      salesReadiness: () =>
        restClient.get('/v1/admin/kyber/gtm/sales-readiness', wrap(unknownSchema)).then(r => r.data),
      customerSuccessOverview: () =>
        restClient.get('/v1/admin/kyber/customer-success/overview', wrap(unknownSchema)).then(r => r.data),
      customerSuccessAccounts: () =>
        restClient.get('/v1/admin/kyber/customer-success/accounts', wrap(unknownSchema)).then(r => r.data),
      expansionOpportunities: () =>
        restClient.get('/v1/admin/kyber/customer-success/expansion-opportunities', wrap(unknownSchema)).then(r => r.data),
      renewalRisks: () =>
        restClient.get('/v1/admin/kyber/customer-success/renewal-risks', wrap(unknownSchema)).then(r => r.data),
      accountPlan: (tenantId: string) =>
        restClient.get(`/v1/admin/kyber/customer-success/account-plans/${tenantId}`, wrap(unknownSchema)).then(r => r.data),
      generateEbr: (tenantId: string) =>
        restClient.post(`/v1/admin/kyber/customer-success/ebr/${tenantId}/generate`, wrap(unknownSchema), {}).then(r => r.data),
      customerSuccessTriggersGenerate: () =>
        restClient.post('/v1/admin/kyber/customer-success/triggers/generate', wrap(unknownSchema), {}).then(r => r.data),
      // ── Security & Governance Command Center ──────────────────────────────
      securityOverview: () =>
        restClient.get('/v1/admin/kyber/security/overview', wrap(unknownSchema)).then(r => r.data),
      securityAuditEvents: (tenantId?: string) =>
        restClient.get(`/v1/admin/kyber/security/audit-events${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
      securityPolicyDecisions: (tenantId?: string) =>
        restClient.get(`/v1/admin/kyber/security/policy-decisions${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
      securityTenantIsolation: (run = false) =>
        restClient.get(`/v1/admin/kyber/security/tenant-isolation${buildQS({ run })}`, wrap(unknownSchema)).then(r => r.data),
      securityOperatorAccess: () =>
        restClient.get('/v1/admin/kyber/security/operator-access', wrap(unknownSchema)).then(r => r.data),
      securityDataRetention: (tenantId?: string) =>
        restClient.get(`/v1/admin/kyber/security/data-retention${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
      securityCreateRetentionPolicy: (body: Record<string, unknown>) =>
        restClient.post('/v1/admin/kyber/security/data-retention/policies', wrap(unknownSchema), body).then(r => r.data),
      securityUpdateRetentionPolicy: (policyId: string, body: Record<string, unknown>) =>
        restClient.patch(`/v1/admin/kyber/security/data-retention/policies/${policyId}`, wrap(unknownSchema), body).then(r => r.data),
      securityDataRequests: (tenantId?: string) =>
        restClient.get(`/v1/admin/kyber/security/data-requests${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
      securityProcessDataRequest: (dataRequestId: string, body: Record<string, unknown>) =>
        restClient.patch(`/v1/admin/kyber/security/data-requests/${dataRequestId}`, wrap(unknownSchema), body).then(r => r.data),
      securityEvidencePacks: (tenantId?: string) =>
        restClient.get(`/v1/admin/kyber/security/governance-evidence-packs${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
      securityGenerateEvidencePack: (body: Record<string, unknown>) =>
        restClient.post('/v1/admin/kyber/security/governance-evidence-packs/generate', wrap(unknownSchema), body).then(r => r.data),
      securityBreakGlassList: (tenantId?: string) =>
        restClient.get(`/v1/admin/kyber/security/break-glass${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
      securityBreakGlassRequest: (body: Record<string, unknown>) =>
        restClient.post('/v1/admin/kyber/security/break-glass/request', wrap(unknownSchema), body).then(r => r.data),
      securityBreakGlassApprove: (requestId: string) =>
        restClient.post(`/v1/admin/kyber/security/break-glass/${requestId}/approve`, wrap(unknownSchema), {}).then(r => r.data),
      securityBreakGlassDeny: (requestId: string, reason = '') =>
        restClient.post(`/v1/admin/kyber/security/break-glass/${requestId}/deny`, wrap(unknownSchema), { reason }).then(r => r.data),
      securityBreakGlassRevoke: (requestId: string) =>
        restClient.post(`/v1/admin/kyber/security/break-glass/${requestId}/revoke`, wrap(unknownSchema), {}).then(r => r.data),

      // ── Reliability command center ─────────────────────────────────────
      reliabilityOverview: () =>
        restClient.get('/v1/admin/kyber/reliability/overview', wrap(unknownSchema)).then(r => r.data),
      reliabilityServices: () =>
        restClient.get('/v1/admin/kyber/reliability/services', wrap(unknownSchema)).then(r => r.data),
      reliabilityPipelines: () =>
        restClient.get('/v1/admin/kyber/reliability/pipelines', wrap(unknownSchema)).then(r => r.data),
      reliabilityQueues: () =>
        restClient.get('/v1/admin/kyber/reliability/queues', wrap(unknownSchema)).then(r => r.data),
      reliabilitySlos: () =>
        restClient.get('/v1/admin/kyber/reliability/slos', wrap(unknownSchema)).then(r => r.data),
      incidents: (status?: string) =>
        restClient.get(`/v1/admin/kyber/incidents${buildQS({ status })}`, wrap(unknownSchema)).then(r => r.data),
      incident: (incidentId: string) =>
        restClient.get(`/v1/admin/kyber/incidents/${incidentId}`, wrap(unknownSchema)).then(r => r.data),
      createIncident: (body: unknown) =>
        restClient.post('/v1/admin/kyber/incidents', wrap(unknownSchema), body).then(r => r.data),
      patchIncident: (incidentId: string, body: unknown) =>
        restClient.patch(`/v1/admin/kyber/incidents/${incidentId}`, wrap(unknownSchema), body).then(r => r.data),
      runbooks: () =>
        restClient.get('/v1/admin/kyber/runbooks', wrap(unknownSchema)).then(r => r.data),
      createRunbook: (body: unknown) =>
        restClient.post('/v1/admin/kyber/runbooks', wrap(unknownSchema), body).then(r => r.data),
      patchRunbook: (runbookId: string, body: unknown) =>
        restClient.patch(`/v1/admin/kyber/runbooks/${runbookId}`, wrap(unknownSchema), body).then(r => r.data),
      postmortems: () =>
        restClient.get('/v1/admin/kyber/postmortems', wrap(unknownSchema)).then(r => r.data),
      createPostmortem: (body: unknown) =>
        restClient.post('/v1/admin/kyber/postmortems', wrap(unknownSchema), body).then(r => r.data),
      patchPostmortem: (postmortemId: string, body: unknown) =>
        restClient.patch(`/v1/admin/kyber/postmortems/${postmortemId}`, wrap(unknownSchema), body).then(r => r.data),

      // ── Intelligence Quality / Drift Detection (aggregate-only) ───────────
      intelligenceQualityOverview: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/overview', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityTenants: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/tenants', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityDriftEvents: (driftType?: string, status?: string) =>
        restClient.get(`/v1/admin/kyber/intelligence-quality/drift-events${buildQS({ drift_type: driftType, status })}`, wrap(unknownSchema)).then(r => r.data),
      intelligenceQualitySchemaDrift: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/schema-drift', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityIdentity: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/identity', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityGraph: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/graph', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityRecommendations: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/recommendations', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityOutcomes: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/outcomes', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityPlaybooks: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/playbooks', wrap(unknownSchema)).then(r => r.data),
      intelligenceQualityContamination: () =>
        restClient.get('/v1/admin/kyber/intelligence-quality/contamination', wrap(unknownSchema)).then(r => r.data),
      acknowledgeDriftEvent: (driftEventId: string) =>
        restClient.post(`/v1/admin/kyber/intelligence-quality/drift-events/${driftEventId}/acknowledge`, wrap(unknownSchema), {}).then(r => r.data),
      resolveDriftEvent: (driftEventId: string, body: unknown = {}) =>
        restClient.post(`/v1/admin/kyber/intelligence-quality/drift-events/${driftEventId}/resolve`, wrap(unknownSchema), body).then(r => r.data),
    },
  },

  // ── Graph — Kyber sees the COMBINED graph of ALL tenants ──────────────────
  //
  // Kyber has omniscient scope: every entity, every tenant, every connection.
  // Aether (tenant layer) sees only its own users.
  //
  // Interaction classes on edges:
  //   H2H — human ↔ human   (referrals, commerce, social, identity links)
  //   H2A — human → agent   (delegation, hiring, configuration)
  //   A2H — agent → human   (purchases on behalf, notifications, reporting)
  //   A2A — agent ↔ agent   (sub-delegation, pipeline calls, A2A payments)
  graph: {
    /**
     * Full entity graph rooted at entityId across ALL tenants.
     * Nodes: human, agent, wallet, device, org, contract.
     * Edges typed with interaction_class (H2H/H2A/A2H/A2A) and
     * relation_type (owns, delegates_to, buys_from, transfers_to, same_person…).
     */
    entityGraph: (entityId: string) =>
      restClient.get(`/v1/entities/${entityId}/graph`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Search all entities across tenants — the global entity registry.
     * Returns nodes with kind, trust_score, cluster_id.
     */
    searchEntities: (query: string, type?: string, limit = 50) =>
      restClient.get(`/v1/entities/search${buildQS({ q: query, type, limit })}`, wrap(z.object({ results: z.array(z.unknown()), total: z.number() }))).then(r => r.data),

    /**
     * Identity cluster for an entity — all probabilistically co-resolved
     * actors, with shared devices, IPs, wallets, and campaigns that form
     * the "collective tissue" between them.
     */
    cluster: (entityId: string) =>
      restClient.get(`/v1/intelligence/entity/${entityId}/cluster`, wrap(unknownSchema)).then(r => r.data),

    /** Resolution cluster — admin view with merge confidence and pending decisions. */
    resolutionCluster: (userId: string) =>
      restClient.get(`/v1/resolution/cluster/${userId}`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Cross-domain fusion profile — unified view of an entity spanning Web2,
     * Web3, and institutional data across ALL tenants.
     * Exposes H2H commerce flows, A2A pipelines, and H2A delegation in one payload.
     */
    fusionProfile: (entityId: string) =>
      restClient.get(`/v1/crossdomain/fusion/profile/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    /** Aggregate financial exposure across all domains (cross-tenant). */
    fusionExposure: (entityId: string) =>
      restClient.get(`/v1/crossdomain/fusion/exposure/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    /** All identity links for an entity — across all tenants. */
    links: (entityId: string, params?: { limit?: number }) =>
      restClient.get(`/v1/crossdomain/links/${entityId}${buildQS({ ...params })}`, wrap(z.object({ entity_id: z.string(), links: z.array(unknownSchema), count: z.number() }))).then(r => r.data.links),

    /**
     * Global high-confidence links — the strongest cross-entity connections
     * in the entire network regardless of tenant boundary.
     * Use to surface "same_person" or "shared_wallet" clusters at scale.
     */
    highConfidenceLinks: (minConfidence = 0.8, limit = 50) =>
      restClient.get(`/v1/crossdomain/links/high-confidence?min_confidence=${minConfidence}&limit=${limit}`, wrap(z.object({ links: z.array(unknownSchema), count: z.number(), min_confidence: z.number() }))).then(r => r.data.links),

    /** All delegation records (grantor or grantee) — H→A, H→H, A→A chains across tenants. */
    delegations: (params: { grantor?: string; grantee?: string; active?: boolean; limit?: number }) =>
      restClient.get(`/v1/delegations${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data as DelegationsResponse),

    validateDelegation: (params: { grantee_entity_id: string; action: string; resource: string; amount?: number }) =>
      restClient.post('/v1/delegations/validate', wrap(unknownSchema), params).then(r => r.data),

    /**
     * Wallet intelligence — risk scores, features, graph neighbourhood for
     * an on-chain address.  Works across all tenants who have ingested this wallet.
     */
    walletProfile: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/profile`, wrap(unknownSchema)).then(r => r.data),

    walletRisk: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/risk`, wrap(unknownSchema)).then(r => r.data),

    /**
     * x402 economic graph — global agent payment flows and net settlement
     * positions across the entire Aether network.
     */
    x402Graph: () =>
      restClient.get('/v1/x402/graph', wrap(unknownSchema)).then(r => r.data),

    agentX402: (agentId: string) =>
      restClient.get(`/v1/x402/agent/${agentId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Investigations (case management — cross-tenant operator view) ──────────
  investigations: {
    create: (body: {
      tenantId: string;
      title: string;
      subjects?: Array<{ kind: string; id: string }>;
      createdBy: string;
    }) => restClient.post('/v1/investigations', unknownSchema, body),

    list: (tenantId: string, params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/investigations${buildQS({ tenantId, ...params })}`, unknownSchema),

    get: (caseId: string, tenantId: string) =>
      restClient.get(`/v1/investigations/${caseId}${buildQS({ tenantId })}`, unknownSchema),

    transitionStatus: (caseId: string, body: {
      tenantId: string;
      status: 'open' | 'triage' | 'active' | 'escalated' | 'closed';
      reason?: string;
    }) => restClient.patch(`/v1/investigations/${caseId}/status`, unknownSchema, body),

    addEvidence: (caseId: string, body: {
      tenantId: string;
      evidence: Array<{ id: string; type: string; source: string }>;
    }) => restClient.post(`/v1/investigations/${caseId}/evidence`, unknownSchema, body),

    addAnnotation: (caseId: string, body: {
      tenantId: string;
      body: string;
      authorId: string;
      entityRefs?: Array<{ kind: string; id: string }>;
    }) => restClient.post(`/v1/investigations/${caseId}/annotations`, unknownSchema, body),
  },

  // ── Graph Intelligence (GraphTraversalEngine-backed routes) ──────────────
  graphIntelligence: {
    traverse: (body: {
      tenantId: string;
      start: { kind: string; id: string; label?: string };
      depth: number;
      direction?: 'in' | 'out' | 'both';
      limit?: number;
    }) => restClient.post('/v1/graph/traverse', unknownSchema, body),

    path: (body: {
      tenantId: string;
      from: { kind: string; id: string; label?: string };
      to: { kind: string; id: string; label?: string };
      maxDepth?: number;
    }) => restClient.post('/v1/graph/path', unknownSchema, body),

    temporal: (body: {
      tenantId: string;
      anchor: { kind: string; id: string; label?: string };
      asOf: string;
      depth?: number;
    }) => restClient.post('/v1/graph/temporal', unknownSchema, body),

    overlay: (body: {
      tenantId: string;
      overlays: string[];
      limit?: number;
    }) => restClient.post('/v1/graph/overlay', unknownSchema, body),

    filter: (body: {
      tenantId: string;
      filter: Record<string, unknown>;
      limit?: number;
    }) => restClient.post('/v1/graph/filter', unknownSchema, body),
  },

  // ── Entity Intelligence (profile, timeline, relationships) ─────────────────
  entityIntelligence: {
    profile: (body: {
      tenantId: string;
      entity: { kind: string; id: string };
      dimensions?: string[];
      consistency?: string;
    }) => restClient.post('/v1/entities/profile', unknownSchema, body),

    timeline: (body: {
      tenantId: string;
      entity: { kind: string; id: string };
      fromTime?: string;
      toTime?: string;
      limit?: number;
      cursor?: string;
    }) => restClient.post('/v1/entities/timeline/query', unknownSchema, body),

    relationships: (body: {
      tenantId: string;
      entity: { kind: string; id: string };
      relationshipTypes?: string[];
      minScore?: number;
      depth?: number;
      limit?: number;
      cursor?: string;
    }) => restClient.post('/v1/entities/relationships/query', unknownSchema, body),
  },

  // ── Event Replay (Bronze-tier source_tag replay) ───────────────────────────
  eventReplay: {
    submit: (body: {
      tenantId: string;
      sourceTag: string;
      fromTime: string;
      toTime?: string;
      eventTypes?: string[];
      dryRun?: boolean;
    }) => restClient.post('/v1/events/replay', unknownSchema, body),

    getJob: (jobId: string, tenantId: string) =>
      restClient.get(`/v1/events/replay/${jobId}${buildQS({ tenantId })}`, unknownSchema),

    listJobs: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/events/replay${buildQS({ tenantId, limit })}`, unknownSchema),

    cancel: (jobId: string, tenantId: string) =>
      restClient.post(`/v1/events/replay/${jobId}/cancel`, unknownSchema, { tenantId }),
  },

  // ── Governance (policy decisions + audit — operator view) ─────────────────
  governance: {
    evaluate: (body: {
      tenantId: string;
      principal: { kind: string; id: string };
      action: string;
      resource: { kind: string; id: string };
      context?: Record<string, unknown>;
      policyIds?: string[];
    }) => restClient.post('/v1/governance/decisions/evaluate', unknownSchema, body),

    listDecisions: (tenantId: string, params?: {
      principal_id?: string;
      allowed?: boolean;
      limit?: number;
    }) => restClient.get(`/v1/governance/decisions${buildQS({ tenantId, ...params })}`, unknownSchema),

    getDecision: (decisionId: string, tenantId: string) =>
      restClient.get(`/v1/governance/decisions/${decisionId}${buildQS({ tenantId })}`, unknownSchema),

    audit: (tenantId: string, params?: { limit?: number; principal_id?: string }) =>
      restClient.get(`/v1/governance/audit${buildQS({ tenantId, ...params })}`, unknownSchema),
  },

  // ── Cognitive Integrity System (CIS) ──────────────────────────────────────
  cis: {
    getHealth: (tenantId?: string) =>
      restClient.get(`/v1/cis/health${tenantId ? buildQS({ tenant_id: tenantId }) : ''}`, wrap(unknownSchema)).then(r => r.data),

    getGlobalHealth: () =>
      restClient.get('/v1/cis/health/global', wrap(unknownSchema)).then(r => r.data),

    getMutations: (params?: { status?: string; agent_id?: string; risk_band?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/cis/mutations${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    getMutation: (mutationId: string) =>
      restClient.get(`/v1/cis/mutations/${mutationId}`, wrap(unknownSchema)).then(r => r.data),

    quarantineMutation: (mutationId: string, reason?: string) =>
      restClient.post(`/v1/cis/mutations/${mutationId}/quarantine`, wrap(unknownSchema), { reason }),

    approveMutation: (mutationId: string, reason?: string) =>
      restClient.post(`/v1/cis/mutations/${mutationId}/approve`, wrap(unknownSchema), { reason }),

    getContamination: () =>
      restClient.get('/v1/cis/contamination', wrap(unknownSchema)).then(r => r.data),

    getForensics: (nodeId: string) =>
      restClient.get(`/v1/cis/forensics/${nodeId}`, wrap(unknownSchema)).then(r => r.data),

    getDrift: (params?: { window?: string; cluster_id?: string; limit?: number }) =>
      restClient.get(`/v1/cis/drift${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    getRetrieval: (params?: { window?: string; model_name?: string; limit?: number }) =>
      restClient.get(`/v1/cis/retrieval${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    getReasoning: (params?: { chain_id?: string; limit?: number }) =>
      restClient.get(`/v1/cis/reasoning${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    getTenantGovernance: (tenantId: string) =>
      restClient.get(`/v1/cis/tenants/${tenantId}/governance`, wrap(unknownSchema)).then(r => r.data),

    wsUrl: () => '/v1/cis/ws/stream' as string,
  },

  // ── Commerce ───────────────────────────────────────────────────────────────
  commerce: {
    recordPayment: (payment: Record<string, unknown>) =>
      restClient.post('/v1/commerce/payments', wrap(unknownSchema), payment).then(r => r.data),

    recordHire: (hire: Record<string, unknown>) =>
      restClient.post('/v1/commerce/hires', wrap(unknownSchema), hire).then(r => r.data),

    feesReport: (period?: string) =>
      restClient.get(`/v1/commerce/fees/report${period ? `?period=${period}` : ''}`, wrap(unknownSchema)).then(r => r.data),

    agentSpend: (agentId: string) =>
      restClient.get(`/v1/commerce/agent/${agentId}/spend`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── SDK Health Monitoring ──────────────────────────────────────────────────
  sdkHealth: {
    fleet: () =>
      restClient.get('/v1/diagnostics/sdk/health', wrap(unknownSchema)).then(r => r.data),

    sdkScore: (sdkId: string) =>
      restClient
        .get(`/v1/diagnostics/sdk/health/${encodeURIComponent(sdkId)}`, wrap(unknownSchema))
        .then(r => r.data),

    silent: () =>
      restClient.get('/v1/diagnostics/sdk/silent', wrap(unknownSchema)).then(r => r.data),

    driftIncidents: (params?: { drift_type?: string; severity?: string; limit?: number }) =>
      restClient
        .get(`/v1/diagnostics/sdk/drift/incidents${buildQS({ ...params })}`, wrap(unknownSchema))
        .then(r => r.data),

    driftReport: () =>
      restClient.get('/v1/diagnostics/sdk/drift/report', wrap(unknownSchema)).then(r => r.data),

    manifest: (params?: { sdk_id?: string; sdk_version?: string; cohort?: string }) =>
      restClient
        .get(`/v1/config/sdk/manifest${buildQS({ ...params })}`, wrap(unknownSchema))
        .then(r => r.data),

    rolloutStatus: () =>
      restClient.get('/v1/config/sdk/rollout', wrap(unknownSchema)).then(r => r.data),
  },
};

// ─── Utility: call API with a typed fallback ─────────────────────────────────
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
