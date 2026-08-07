/**
 * AETHER tenant API endpoints.
 *
 * Covers the full contextual data surface for a tenant's users:
 *   - Profile & Identity (all sub-resources: sessions, devices, platforms,
 *     wallets (Web3), financials (Web2+Web3), journeys, loyalty, intelligence)
 *   - Consent & Privacy
 *   - Rewards & Campaigns (funnel, drop-off, attribution "where")
 *   - Behavioural "Why" (signals, expectations, explain)
 *   - Graph & Relationships (H2H / H2A / A2H / A2A edges, delegation chains,
 *     identity clusters, collective tissue)
 *   - Web3 & On-Chain (wallet balances + tx history, protocols, oracle, x402)
 *   - Ingestion (SDK event capture)
 *
 * Kyber is the all-tenant aggregated layer; Aether is what the tenant sees
 * about their own users.
 */
import { z } from 'zod';
import { restClient } from './rest/client';
import type {
  SessionsResponse, DevicesResponse, JourneysResponse, WalletsResponse,
  RelationshipsResponse, DelegationsResponse,
  UnifiedFinancialProfile, IntelligenceProfile,
  WalletRiskProfile, Web3WalletProfile, EntityCluster,
  AttributionJourney, WhyExplanation, BehavioralSignal,
  Profile360Response, EntityGraph,
} from '@aether/shared';

// ─── Auth grant shapes (trust-plane sessions vs legacy API keys) ─────────────

/** Durable, revocable trust-plane session issued by the backend on human auth. */
export interface HumanSessionGrant {
  session_id: string;
  /** Opaque "sess_..." token — server-tracked, NOT a reusable API key. */
  token: string;
  credential_class?: string;
  idle_expires_at?: string;
  absolute_expires_at?: string;
}

/**
 * Human auth response: a trust-plane `session` when the backend runs with
 * HUMAN_SESSIONS_ENABLED, or a legacy reusable `api_key` when the flag is off.
 */
export interface AuthGrantResponse {
  tenant_id?: string;
  session?: HumanSessionGrant;
  api_key?: string;
  message?: string;
  name?: string;
}

// ─── Response wrapper ────────────────────────────────────────────────────────
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const unknownSchema = z.unknown();

// Customer settings responses are validated at the transport boundary.  Keep
// these schemas aligned with the explicit DTOs returned by services/me and
// services/billing; callers must never guess between legacy field names.
const apiKeySchema = z.object({
  id: z.string(),
  name: z.string(),
  tier: z.string(),
  permissions: z.array(z.string()),
  platform: z.string().nullable(),
  last_used_at: z.string().nullable(),
});

const billingPlanSchema = z.object({
  plan_id: z.string(),
  display_name: z.string(),
  price_monthly: z.number(),
  currency: z.string(),
  contact_sales: z.boolean(),
  included_usage: z.number(),
  rate_limit_rpm: z.number(),
  monthly_quota: z.number(),
  burst_rpm: z.number(),
  service_count: z.number(),
  target_user: z.string(),
});

const invoiceSchema = z.object({
  id: z.string(),
  status: z.string(),
  currency: z.string(),
  amount_due: z.number(),
  amount_paid: z.number(),
  amount_remaining: z.number(),
  period_start: z.string(),
  period_end: z.string(),
  created_at: z.string(),
  hosted_invoice_url: z.string().url().nullable(),
  invoice_pdf_url: z.string().url().nullable(),
});

const organizationProfileSchema = z.object({
  organization_id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  slug: z.string().nullable(),
  description: z.string().nullable(),
  owner_user_id: z.string().nullable(),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

const organizationMemberSchema = z.object({
  member_id: z.string(),
  tenant_id: z.string(),
  user_id: z.string(),
  email: z.string().nullable(),
  display_name: z.string().nullable(),
  role: z.enum(['owner', 'admin', 'member', 'viewer']),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

const organizationInvitationSchema = z.object({
  invitation_id: z.string(),
  tenant_id: z.string(),
  email: z.string(),
  role: z.enum(['owner', 'admin', 'member', 'viewer']),
  status: z.string(),
  invited_by: z.string(),
  expires_at: z.string(),
  revoked_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

const paginationSchema = z.object({
  limit: z.number(),
  offset: z.number(),
  total: z.number(),
  has_more: z.boolean(),
});

const customerWebhookReadSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  url: z.string(),
  events: z.array(z.string()),
  active: z.boolean(),
  secret_configured: z.boolean(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

const customerWebhookCreateResponseSchema = customerWebhookReadSchema.extend({
  secret: z.string(),
});

const webhookPageSchema = z.object({
  webhooks: z.array(customerWebhookReadSchema),
  pagination: paginationSchema,
});

const webhookTestResultSchema = z.object({
  status: z.string(),
  success: z.boolean(),
  webhook_id: z.string(),
  tenant_id: z.string(),
  idempotency_key: z.string(),
  attempts: z.number(),
  status_code: z.number().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
  error: z.string().nullable().optional(),
  attempt_id: z.string().nullable().optional(),
});

const deletionDomainSchema = z.object({
  domain: z.string(),
  repository: z.string(),
  mode: z.string(),
  status: z.string(),
  action: z.string(),
  reason: z.string().nullable().optional(),
  records_affected: z.number(),
  completed_at: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
});

const deletionWorkflowSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  requested_at: z.string(),
  recovery_until: z.string(),
  status: z.enum(['recovery', 'processing', 'completed', 'failed', 'cancelled']),
  actor_id: z.string(),
  actor_type: z.string(),
  reauth_evidence: z.object({
    verified: z.boolean(),
    method: z.string(),
    verified_at: z.string(),
    assurance_level: z.string(),
    provider: z.string().nullable().optional(),
  }),
  storage_results: z.object({
    domains: z.record(z.string(), deletionDomainSchema),
    registry_version: z.number(),
  }),
  retry_count: z.number(),
  completed_at: z.string().nullable(),
  failed_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  erasure_manifest: z.object({
    version: z.number(),
    recovery_window_days: z.number(),
    fully_erased: z.boolean(),
    domains: z.record(z.string(), deletionDomainSchema),
    completion: z.string().optional(),
  }),
});

export type CustomerApiKey = z.infer<typeof apiKeySchema>;
export type CustomerBillingPlan = z.infer<typeof billingPlanSchema>;
export type CustomerInvoice = z.infer<typeof invoiceSchema>;
export type OrganizationProfile = z.infer<typeof organizationProfileSchema>;
export type OrganizationMember = z.infer<typeof organizationMemberSchema>;
export type OrganizationInvitation = z.infer<typeof organizationInvitationSchema>;
export type CustomerWebhook = z.infer<typeof customerWebhookReadSchema>;
export type CustomerWebhookCreated = z.infer<typeof customerWebhookCreateResponseSchema>;
export type CustomerWebhookPage = z.infer<typeof webhookPageSchema>;
export type CustomerWebhookTestResult = z.infer<typeof webhookTestResultSchema>;
export type AccountDeletionWorkflow = z.infer<typeof deletionWorkflowSchema>;

const demoSeedStatusSchema = z.object({
  seeded: z.boolean(),
  is_demo_tenant: z.boolean(),
  tenant_id: z.string(),
  tenant_name: z.string().nullable(),
  data_origin: z.string().nullable(),
  namespace: z.string(),
  dataset_version: z.string(),
  checksum: z.string(),
  run_count: z.number(),
  owned_record_count: z.number(),
  latest_run: z.object({
    seed_run_id: z.string().nullable(),
    dataset_version: z.string().nullable(),
    namespace: z.string().nullable(),
    tenant_id: z.string().nullable(),
    checksum: z.string().nullable(),
    status: z.string().nullable(),
    started_at: z.string().nullable(),
    completed_at: z.string().nullable(),
    inserted_counts: z.record(z.string(), z.number()),
    updated_counts: z.record(z.string(), z.number()),
    skipped_counts: z.record(z.string(), z.number()),
  }).nullable(),
});

export type DemoSeedStatus = z.infer<typeof demoSeedStatusSchema>;

// Economic-domain routes return raw {items, count} (no APIResponse envelope)
const listSchema = z.object({ items: z.array(z.unknown()), count: z.number() });

const buildQS = (params: Record<string, string | number | boolean | undefined>) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

// ─── Semantic intelligence shapes ────────────────────────────────────────────
// Mirrors services/semantic_intelligence/models.py (EvidenceRef,
// EntitySemanticState) and the /v1/graph/semantic-overlay route payload.

const semanticEvidenceRefSchema = z.object({
  evidence_id: z.string(),
  source_type: z.string(),
  source_ref: z.string(),
  observed_at: z.string(),
  confidence: z.number(),
}).passthrough();

/** Durable Gold-tier weighted semantic state for an entity. */
const entitySemanticStateSchema = z.object({
  state_id: z.string(),
  tenant_id: z.string(),
  entity_ref: z.string(),
  entity_type: z.string(),
  subject_ref: z.string(),
  window_start: z.string(),
  window_end: z.string(),
  active_topics: z.array(z.string()),
  dominant_narratives: z.array(z.string()),
  stance_distribution: z.record(z.string(), z.number()),
  intent_distribution: z.record(z.string(), z.number()),
  /** "insufficient_data" when no semantic observations exist yet. */
  semantic_summary: z.string(),
  semantic_baseline: z.record(z.string(), z.unknown()),
  semantic_delta: z.record(z.string(), z.unknown()),
  persistence: z.string(),
  volatility: z.number(),
  observation_count: z.number(),
  unique_source_count: z.number(),
  model_mix: z.record(z.string(), z.number()),
  confidence: z.number(),
  freshness: z.string(),
  evidence_refs: z.array(semanticEvidenceRefSchema),
  version: z.number(),
  computed_at: z.string(),
}).passthrough();

/** GET /v1/profile/{user_id}/semantic — empty-but-shaped when not computed. */
const profileSemanticSchema = z.object({
  user_id: z.string(),
  semantic: entitySemanticStateSchema,
  computed: z.boolean(),
  provenance: z.object({ sources: z.array(z.string()) }).passthrough().optional(),
}).passthrough();

const semanticNodeOverlaySchema = z.object({
  entity_ref: z.string(),
  stance: z.string(),
  topics: z.array(z.string()),
  confidence: z.number(),
  valid_from: z.string(),
  evidence_refs: z.array(semanticEvidenceRefSchema),
}).passthrough();

/** POST /v1/graph/semantic-overlay response payload. */
const semanticOverlaySchema = z.object({
  overlay_type: z.string(),
  node_overlays: z.array(semanticNodeOverlaySchema),
  edge_overlays: z.array(z.unknown()),
  partial: z.boolean(),
  causal_confidence: z.string(),
}).passthrough();

export type SemanticEvidenceRef = z.infer<typeof semanticEvidenceRefSchema>;
export type EntitySemanticState = z.infer<typeof entitySemanticStateSchema>;
export type ProfileSemanticResponse = z.infer<typeof profileSemanticSchema>;
export type SemanticNodeOverlay = z.infer<typeof semanticNodeOverlaySchema>;
export type SemanticOverlayResponse = z.infer<typeof semanticOverlaySchema>;

// ─── API ─────────────────────────────────────────────────────────────────────
export const api = {

  demoSeed: {
    status: () =>
      restClient.get('/v1/demo-seed/status', wrap(demoSeedStatusSchema)).then(r => r.data),
  },

  // ── System status — tenant-safe reliability visibility ────────────────────
  status: {
    overview: () => restClient.get('/v1/status', wrap(unknownSchema)).then(r => r.data),
    incidents: () => restClient.get('/v1/status/incidents', wrap(unknownSchema)).then(r => r.data),
    dataFreshness: () => restClient.get('/v1/status/data-freshness', wrap(unknownSchema)).then(r => r.data),
    integrations: () => restClient.get('/v1/status/integrations', wrap(unknownSchema)).then(r => r.data),
  },

  valueReview: {
    overview: () => restClient.get('/v1/value-review', wrap(unknownSchema)).then(r => r.data),
    summary: () => restClient.get('/v1/value-review/summary', wrap(unknownSchema)).then(r => r.data),
    recommendations: () => restClient.get('/v1/value-review/recommendations', wrap(unknownSchema)).then(r => r.data),
    playbooks: () => restClient.get('/v1/value-review/playbooks', wrap(unknownSchema)).then(r => r.data),
    nextSteps: () => restClient.get('/v1/value-review/next-steps', wrap(unknownSchema)).then(r => r.data),
  },

  // ─── Security & Governance (tenant-scoped only) ────────────────────────────
  security: {
    myPermissions: () => restClient.get('/v1/security/me/permissions', wrap(unknownSchema)).then(r => r.data),
    auditEvents: (limit = 50) => restClient.get(`/v1/security/audit-events${buildQS({ limit })}`, wrap(unknownSchema)).then(r => r.data),
    policies: (limit = 50) => restClient.get(`/v1/security/policies${buildQS({ limit })}`, wrap(unknownSchema)).then(r => r.data),
    dataRetention: () => restClient.get('/v1/security/data-retention', wrap(unknownSchema)).then(r => r.data),
    dataRequests: (limit = 50) => restClient.get(`/v1/security/data-requests${buildQS({ limit })}`, wrap(unknownSchema)).then(r => r.data),
    createDataRequest: (body: Record<string, unknown>) => restClient.post('/v1/security/data-requests', wrap(unknownSchema), body).then(r => r.data),
  },

  // ─── Data Quality / Intelligence Quality (tenant-scoped only) ──────────────
  dataQuality: {
    overview: () => restClient.get('/v1/data-quality/overview', wrap(unknownSchema)).then(r => r.data),
    events: () => restClient.get('/v1/data-quality/events', wrap(unknownSchema)).then(r => r.data),
    schema: () => restClient.get('/v1/data-quality/schema', wrap(unknownSchema)).then(r => r.data),
    identity: () => restClient.get('/v1/data-quality/identity', wrap(unknownSchema)).then(r => r.data),
    graph: () => restClient.get('/v1/data-quality/graph', wrap(unknownSchema)).then(r => r.data),
    profile: () => restClient.get('/v1/data-quality/profile', wrap(unknownSchema)).then(r => r.data),
    recommendations: () => restClient.get('/v1/data-quality/recommendations', wrap(unknownSchema)).then(r => r.data),
    outcomes: () => restClient.get('/v1/data-quality/outcomes', wrap(unknownSchema)).then(r => r.data),
    playbooks: () => restClient.get('/v1/data-quality/playbooks', wrap(unknownSchema)).then(r => r.data),
  },

  // ─── Integrations / Connectors (non-SDK ingestion, tenant-scoped) ──────────
  connectors: {
    list: () => restClient.get('/v1/integrations/connectors', wrap(unknownSchema)).then(r => r.data),
    get: (t: string) => restClient.get(`/v1/integrations/connectors/${t}`, wrap(unknownSchema)).then(r => r.data),
    configure: (t: string, body: Record<string, unknown>) => restClient.put(`/v1/integrations/connectors/${t}`, wrap(unknownSchema), body).then(r => r.data),
    test: (t: string) => restClient.post(`/v1/integrations/connectors/${t}/test`, wrap(unknownSchema), {}).then(r => r.data),
    sync: (t: string, opts?: { since?: string }) => restClient.post(`/v1/integrations/connectors/${t}/sync${opts?.since ? `?since=${encodeURIComponent(opts.since)}` : ''}`, wrap(unknownSchema), {}).then(r => r.data),
    /** Durable sync-run history — the customer-visible sync progress surface (§12.4). */
    syncRuns: (t: string, limit = 50) =>
      restClient.get(`/v1/integrations/connectors/${t}/sync-runs?limit=${limit}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Profile — full + all contextual sub-resources ─────────────────────────
  profile: {
    /** Full holistic profile — identity, consent, timeline, graph, intelligence, lake data. */
    full: (userId: string, opts?: { timeline_limit?: number }) =>
      restClient.get(`/v1/profile/${userId}?include_timeline=true&include_graph=true&include_intelligence=true&include_lake=true${opts?.timeline_limit ? `&timeline_limit=${opts.timeline_limit}` : ''}`, wrap(unknownSchema)).then(r => r.data),

    /** Dashboard-ready snapshot — frequency, recency, top events, loyalty tier, risk scores. */
    summary: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/summary`, wrap(unknownSchema)).then(r => r.data),

    /** Chronological event stream. */
    timeline: (userId: string, params?: { limit?: number; event_type?: string }) =>
      restClient.get(`/v1/profile/${userId}/timeline${buildQS({ ...params })}`, wrap(z.object({ user_id: z.string(), events: z.array(z.unknown()), count: z.number() }))).then(r => r.data),

    /** Graph neighbourhood — identity links, ownership, delegation edges. */
    graph: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/graph`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Session rollups for the user — device type, OS, browser, platform,
     * geo (country/region/city, VPN/proxy flags), entry/exit URL, referrer,
     * UTM/campaign context, duration and page-view counts.
     */
    sessions: (userId: string, limit = 20) =>
      restClient.get(`/v1/profile/${userId}/sessions?limit=${limit}`, wrap(unknownSchema)).then(r => r.data as SessionsResponse),

    /** Observed devices — deterministic logins + probabilistic fingerprint matches. */
    devices: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/devices`, wrap(unknownSchema)).then(r => r.data as DevicesResponse),

    /** Platform distribution — web / iOS / Android / SDK / API broken down by event count. */
    platforms: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/platforms`, wrap(unknownSchema)).then(r => r.data),

    /** Cross-session journey chains — steps, drop-off flags, campaign linkage ("where").
     *  Backed by the persisted Profile360 aggregator; the in-memory journey
     *  stitcher (/v1/journeys/*) is not yet wired to ingestion, so reading from
     *  it here would drop existing journey-chain data. */
    journeys: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/journeys`, wrap(unknownSchema)).then(r => r.data as JourneysResponse),

    /** Canonical versioned journey used by Profile 360 and Journey Explorer. */
    unifiedJourney: (
      userId: string,
      params?: { family?: string; after?: string; before?: string; limit?: number; cursor?: string },
    ) =>
      restClient.get(
        `/v1/profile/${encodeURIComponent(userId)}/unified-journey${buildQS({ ...params })}`,
        wrap(unknownSchema),
      ).then(r => r.data),

    /**
     * Web3 wallet profiles for every wallet linked to the user.
     * Each wallet entry includes: token balances, recent on-chain transactions,
     * protocol interactions (DEX swaps, lending, staking, governance votes),
     * NFT holdings, wallet risk score, and Web3 loyalty signals.
     */
    wallets: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/wallets`, wrap(unknownSchema)).then(r => r.data as WalletsResponse),

    /** All identifiers — wallets, emails, device IDs, session IDs, social handles, customer IDs. */
    identifiers: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/identifiers`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Loyalty & rewards — tier (bronze/silver/gold/platinum/diamond),
     * points balance, rewards earned/claimed, campaigns participated,
     * lifetime value, first/last activity.  Web2 + Web3 rewards unified.
     */
    rewards: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/rewards`, wrap(unknownSchema)).then(r => r.data),

    /**
     * Financial profile (Web2 + Web3 unified):
     *   Web2 — payment history, subscription value, refunds, LTV
     *   Web3 — on-chain inflows/outflows by asset, transfers, LP positions,
     *           settlements, top counterparties and protocol spend
     */
    financials: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/financials`, wrap(unknownSchema)).then(r => r.data as UnifiedFinancialProfile),

    /**
     * Typed relationship edges for this entity:
     * H2H (referrals, commerce), H2A (delegation, agent hiring),
     * A2H (agent notifies/purchases for human), A2A (agent pipelines).
     * Each edge carries relation_type, weight, confidence, volume_usd.
     */
    relationships: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/relationships`, wrap(unknownSchema)).then(r => r.data as RelationshipsResponse),

    /** Protocol interactions derived from event stream + economic graph. */
    protocols: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/protocols`, wrap(unknownSchema)).then(r => r.data),

    /** Intelligence layer — risk score, trust score, anomaly score, ML feature values. */
    intelligence: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/intelligence`, wrap(unknownSchema)).then(r => r.data as IntelligenceProfile),

    /**
     * Profile360 semantic dimension — durable weighted semantic state:
     * active topics, stance/intent distribution, summary, confidence and
     * freshness from the semantic Gold-tier reducer. Empty-but-shaped
     * (computed=false, semantic_summary="insufficient_data") when no
     * semantic observations exist yet.
     */
    semantic: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/semantic`, wrap(profileSemanticSchema)).then(r => r.data),

    recommendations: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/recommendations`, wrap(unknownSchema)).then(r => r.data),

    outcomes: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/outcomes`, wrap(unknownSchema)).then(r => r.data),

    outcomeLedger: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/outcome-ledger`, wrap(unknownSchema)).then(r => r.data),

    /** Data provenance — source attribution for every data point in the profile. */
    provenance: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/provenance`, wrap(unknownSchema)).then(r => r.data),

    /** Deep-drill on any linked object (e.g. a specific wallet, journey, device). */
    drill: (userId: string, objectType: string, objectId: string) =>
      restClient.get(`/v1/profile/${userId}/drill/${objectType}/${objectId}`, wrap(unknownSchema)).then(r => r.data),

    /** Gold-tier data lake view for a specific domain. */
    lake: (userId: string, domain: 'identity' | 'market' | 'onchain' | 'social') =>
      restClient.get(`/v1/profile/${userId}/lake/${domain}`, wrap(unknownSchema)).then(r => r.data),

    resolve: (params: { wallet?: string; email?: string; device?: string; session?: string; social?: string; customer?: string }) =>
      restClient.get(`/v1/profile/resolve${buildQS(params)}`, wrap(z.object({ resolved_user_id: z.string() }))).then(r => r.data),

    tier: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/tier${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    assetComposition: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/asset-composition${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    pnl: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/pnl${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    tradingProfile: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/trading-profile${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    locationHistory: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/location-history${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    temporalHeatmap: (userId: string, window = '90d') =>
      restClient.get(`/v1/profile/${userId}/temporal-heatmap${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    journeyEconomics: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/journey-economics${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    devicePerformance: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/device-performance${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    funnel: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/funnel${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    timeToConvert: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/time-to-convert${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    web2Profile: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/web2${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    protocolMetrics: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/protocol-metrics${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    governanceActivity: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/governance-activity${buildQS({ window })}`, wrap(unknownSchema)).then(r => r.data),
    quality: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/quality`, wrap(unknownSchema)).then(r => r.data),
    dataFreshness: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/data-freshness`, wrap(unknownSchema)).then(r => r.data),
    dataQuality: (entityId: string) =>
      restClient.get(`/v1/profile/${entityId}/data-quality`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Profile360 normalized surfaces ─────────────────────────────────────────
  profile360: {
    full: (entityType: string, entityId: string) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}?include=identity,financial,graph,timeline,analytics`, wrap(unknownSchema)).then(r => r.data as Profile360Response),

    graph: (entityType: string, entityId: string, params?: { cursor?: string; limit?: number }) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}/graph${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    timeline: (entityType: string, entityId: string, params?: { cursor?: string; limit?: number; type?: string }) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}/timeline${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Identity ───────────────────────────────────────────────────────────────
  identity: {
    getProfile: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}`, wrap(unknownSchema)).then(r => r.data),

    graphNeighborhood: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}/graph`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Resolution (identity cluster — read-only for tenants) ─────────────────
  resolution: {
    cluster: (userId: string) =>
      restClient.get(`/v1/resolution/cluster/${userId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Graph & Relationships (H2H / H2A / A2H / A2A) ─────────────────────────
  graph: {
    /**
     * Entity graph for the user — nodes and edges covering all H2H, H2A, A2H
     * and A2A relationships: ownership, delegation, commerce, referral,
     * identity links, and financial flows.
     */
    entityGraph: (entityId: string) =>
      restClient.get(`/v1/entities/${entityId}/graph`, wrap(unknownSchema)).then(r => r.data as EntityGraph),

    /**
     * Identity cluster — entities probabilistically resolved to the same
     * real-world actor, with shared tissue (devices, IPs, wallets, campaigns).
     */
    cluster: (entityId: string) =>
      restClient.get(`/v1/resolution/cluster/${entityId}`, wrap(unknownSchema)).then(r => r.data as EntityCluster),

    /**
     * Identity links for an entity — H2H same-person, shares_device, shares_wallet.
     * Each link has interaction_class, weight, and confidence.
     */
    links: (entityId: string, limit = 50) =>
      restClient.get(`/v1/crossdomain/links/${entityId}?limit=${limit}`, wrap(z.object({ entity_id: z.string(), links: z.array(unknownSchema), count: z.number() }))).then(r => r.data.links),

    /**
     * All delegation records involving this entity (as grantor or grantee).
     * Exposes H→A grants, H→H sub-delegation, and A→A pipelines.
     */
    delegations: (params: { grantor?: string; grantee?: string; active?: boolean; limit?: number }) =>
      restClient.get(`/v1/delegations${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data as DelegationsResponse),

    /** Validate whether a delegated action is in scope for a grantee. */
    validateDelegation: (params: { grantee_entity_id: string; action: string; resource: string; amount?: number }) =>
      restClient.post('/v1/delegations/validate', wrap(unknownSchema), params).then(r => r.data),

    /**
     * Semantic sentiment overlay for graph / journey views — per-node stance,
     * topics, confidence and evidence refs for a subject's semantic
     * observations. Entity-level only (per-step annotation is not exposed).
     */
    semanticOverlay: (body: { subject_ref: string }) =>
      restClient.post('/v1/graph/semantic-overlay', wrap(semanticOverlaySchema), body).then(r => r.data),

    /** Cross-domain fusion profile — unified view across Web2, Web3, and institutional data. */
    fusionProfile: (entityId: string) =>
      restClient.get(`/v1/crossdomain/fusion/profile/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    /** Financial exposure across all domains. */
    fusionExposure: (entityId: string) =>
      restClient.get(`/v1/crossdomain/fusion/exposure/${entityId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Behavioural "Why" ──────────────────────────────────────────────────────
  behavioral: {
    /** Full behavioural scan across all signal families. */
    entity: (entityId: string) =>
      restClient.get(`/v1/behavioral/entity/${entityId}`, wrap(unknownSchema)).then(r => r.data as { entity_id: string; signals: BehavioralSignal[] }),

    /** Signals filtered by family (intent_residue, wallet_friction, continuity, etc). */
    signals: (entityId: string, params?: { family?: string; limit?: number }) =>
      restClient.get(`/v1/behavioral/entity/${entityId}/signals${buildQS({ ...params })}`, wrap(z.object({ entity_id: z.string(), signals: z.array(z.unknown()), count: z.number() }))).then(r => r.data as { entity_id: string; signals: BehavioralSignal[]; count: number }),

    /** Trigger a full behavioural re-scan. */
    scan: (entityId: string) =>
      restClient.post(`/v1/behavioral/scan/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    /** Latest behaviour snapshot. */
    snapshot: (entityId: string) =>
      restClient.get(`/v1/behavior/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    /** Historical behaviour snapshots. */
    history: (entityId: string, params?: { window?: string; limit?: number }) =>
      restClient.get(`/v1/behavior/${entityId}/history${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Expectations ("Why is this entity unusual?") ───────────────────────────
  expectations: {
    entity: (entityId: string) =>
      restClient.get(`/v1/expectations/entity/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    signals: (entityId: string, params?: { signal_type?: string; limit?: number }) =>
      restClient.get(`/v1/expectations/entity/${entityId}/signals${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    /** Human-readable explanation of why this entity is anomalous. */
    explain: (entityId: string) =>
      restClient.get(`/v1/expectations/entity/${entityId}/explain`, wrap(unknownSchema)).then(r => r.data as WhyExplanation),

    scan: (entityId: string) =>
      restClient.post(`/v1/expectations/scan/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    getSignal: (signalId: string) =>
      restClient.get(`/v1/expectations/signal/${signalId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Consent & Privacy ──────────────────────────────────────────────────────
  consent: {
    getProfile: (userId: string) =>
      restClient.get(`/v1/consent/records/${userId}`, wrap(z.object({
        user_id: z.string(),
        purposes: z.array(z.string()),
        granted: z.boolean(),
        updated_at: z.string().optional(),
        version: z.string().optional(),
      }).passthrough())).then(r => r.data),

    update: (userId: string, purposes: string[], granted: boolean, source = 'ui') =>
      restClient.post('/v1/consent/records', wrap(unknownSchema), { user_id: userId, purposes, granted, source }),

    submitDsr: (userId: string, requestType: 'access' | 'deletion' | 'portability', details?: Record<string, unknown>) =>
      restClient.post('/v1/consent/dsr', wrap(unknownSchema), { user_id: userId, request_type: requestType, ...details }),

    getDsrRequest: (requestId: string) =>
      restClient.get(`/v1/consent/dsr/${requestId}`, wrap(unknownSchema)).then(r => r.data),

    listDsrRequests: (params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/consent/dsr${buildQS({ ...params })}`, wrap(z.object({ requests: z.array(z.unknown()), count: z.number() }))).then(r => r.data),
  },

  // ── Campaigns ──────────────────────────────────────────────────────────────
  campaigns: {
    list: (params?: { status?: string; limit?: number; offset?: number; origin?: string; platform?: string; mapping_quality?: string }) =>
      restClient.get(`/v1/campaigns${buildQS({ ...params })}`, wrap(z.object({ campaigns: z.array(z.unknown()), total: z.number() }))).then(r => r.data),

    get: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}`, wrap(unknownSchema)).then(r => r.data),

    create: (campaign: Record<string, unknown>) =>
      restClient.post('/v1/campaigns', wrap(unknownSchema), campaign).then(r => r.data),

    update: (campaignId: string, updates: Record<string, unknown>) =>
      restClient.patch(`/v1/campaigns/${campaignId}`, wrap(unknownSchema), updates).then(r => r.data),

    delete: (campaignId: string) =>
      restClient.delete(`/v1/campaigns/${campaignId}`, wrap(z.object({ deleted: z.boolean() }))),

    externalRefs: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}/external-refs`, wrap(unknownSchema)).then(r => r.data),

    aliases: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}/aliases`, wrap(unknownSchema)).then(r => r.data),

    createAlias: (campaignId: string, body: { alias_type: string; alias_value: string; platform?: string; source?: string; medium?: string }) =>
      restClient.post(`/v1/campaigns/${campaignId}/aliases`, wrap(unknownSchema), body).then(r => r.data),

    expireAlias: (campaignId: string, aliasId: string) =>
      restClient.delete(`/v1/campaigns/${campaignId}/aliases/${aliasId}`, wrap(unknownSchema)),

    quality: () =>
      restClient.get('/v1/campaign-quality', wrap(unknownSchema)).then(r => r.data),

    touchpoint: (campaignId: string, tp: { channel?: string; source?: string; user_id?: string; session_id?: string; event_type?: string; is_conversion?: boolean; revenue_usd?: number; timestamp?: string; properties?: Record<string, unknown> }) =>
      restClient.post(`/v1/campaigns/${campaignId}/touchpoints`, wrap(unknownSchema), tp).then(r => r.data),

    /**
     * Multi-touch attribution — surfaces the "where" of a conversion.
     * Models: multi_touch | first_touch | last_touch | linear | time_decay.
     * Returns weighted credits per channel/source/campaign.
     */
    attribution: (campaignId: string, params?: { model?: string; start_date?: string; end_date?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/attribution${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    // ── Campaign 360 Exploration ──────────────────────────────────────────────

    overview: (campaignId: string, params?: { time_start?: string; time_end?: string; attribution_model?: string; attribution_run_id?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/overview${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    population: (campaignId: string, params?: { population?: string; channel?: string; cluster_id?: string; time_start?: string; time_end?: string; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/population${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    clusters: (campaignId: string, params?: { attribution_run_id?: string; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/clusters${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    entities: (campaignId: string, params?: { entity_type?: string; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/entities${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    journeys: (campaignId: string, params?: { time_start?: string; time_end?: string; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/journeys${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    conversions: (campaignId: string, params?: { cluster_id?: string; conversion_type?: string; status?: string; after?: string; before?: string; include_unattributed?: boolean; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/conversions${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    // ── Communications Intelligence (Campaign 360 Messages surface) ──────────

    messages: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}/messages`, wrap(unknownSchema)).then(r => r.data),

    messageDetail: (campaignId: string, externalMessageId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}/messages/${encodeURIComponent(externalMessageId)}`, wrap(unknownSchema)).then(r => r.data),

    links: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}/links`, wrap(unknownSchema)).then(r => r.data),

    commsFunnel: (campaignId: string) =>
      restClient.get(`/v1/campaigns/${campaignId}/comms-funnel`, wrap(unknownSchema)).then(r => r.data),

    commsPopulation: (campaignId: string, params?: { stage?: string; bounced?: boolean; suppressed?: boolean; unsubscribed?: boolean; complained?: boolean; human_qualified?: boolean; limit?: number }) =>
      restClient.get(`/v1/campaigns/${campaignId}/comms-population${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Communications Intelligence ─────────────────────────────────────────────
  comms: {
    health: () =>
      restClient.get('/v1/comms/health', wrap(unknownSchema)).then(r => r.data),

    entityCommunications: (entityId: string, params?: { channel?: string; category?: string; direction?: string; campaign_id?: string; state?: string; human_qualified?: boolean; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/profile/${entityId}/communications${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    entityCommunicationState: (entityId: string, params?: { channel?: string; scope?: string }) =>
      restClient.get(`/v1/profile/${entityId}/communication-state${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    // Cross-channel initiatives (macro rollup over canonical campaigns)
    listInitiatives: (limit = 50) =>
      restClient.get(`/v1/comms/initiatives?limit=${limit}`, wrap(unknownSchema)).then(r => r.data),

    createInitiative: (body: { name: string; description?: string; campaign_ids?: string[] }) =>
      restClient.post('/v1/comms/initiatives', wrap(unknownSchema), body).then(r => r.data),

    initiativeRollup: (initiativeId: string) =>
      restClient.get(`/v1/comms/initiatives/${initiativeId}/rollup`, wrap(unknownSchema)).then(r => r.data),

    /** Tenant comms plan entitlement + current usage + quota state (§20). */
    entitlement: () =>
      restClient.get('/v1/comms/entitlement', wrap(unknownSchema)).then(r => r.data),

    /** Canonical suppression ledger (provider-reported vs Aether-enforced) (§16). */
    suppressions: (limit = 200) =>
      restClient.get(`/v1/comms/suppressions?limit=${limit}`, wrap(unknownSchema)).then(r => r.data),

    /** Provider identities awaiting mapping review (§13). */
    provisionalIdentities: (limit = 100) =>
      restClient.get(`/v1/comms/identities/provisional?limit=${limit}`, wrap(unknownSchema)).then(r => r.data),

    /** Map a provisional provider identity to a canonical entity (§13). */
    resolveIdentity: (identityId: string, canonicalEntityId: string) =>
      restClient.post(`/v1/comms/identities/${identityId}/resolve`, wrap(unknownSchema), { canonical_entity_id: canonicalEntityId }).then(r => r.data),
  },

  // ── Campaign Sources (paid-media connectors) ───────────────────────────────
  campaignSources: {
    list: () =>
      restClient.get('/v1/campaign-sources', wrap(unknownSchema)).then(r => r.data),
    create: (body: { platform: string; connector_id: string; credentials?: Record<string, unknown>; label?: string }) =>
      restClient.post('/v1/campaign-sources', wrap(unknownSchema), body).then(r => r.data),
    health: (connectorId: string) =>
      restClient.get(`/v1/campaign-sources/${connectorId}/health`, wrap(unknownSchema)).then(r => r.data),
    sync: (connectorId: string) =>
      restClient.post(`/v1/campaign-sources/${connectorId}/sync`, wrap(unknownSchema), {}).then(r => r.data),
  },

  // ── Mapping Review ──────────────────────────────────────────────────────────
  mappingReview: {
    list: (params?: { status?: string; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/mapping-review${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
    resolve: (reviewId: string, body: { campaign_id: string; note?: string }) =>
      restClient.post(`/v1/mapping-review/${reviewId}/resolve`, wrap(unknownSchema), body).then(r => r.data),
    ignore: (reviewId: string, body?: { note?: string }) =>
      restClient.post(`/v1/mapping-review/${reviewId}/ignore`, wrap(unknownSchema), body ?? {}).then(r => r.data),
    reopen: (reviewId: string) =>
      restClient.post(`/v1/mapping-review/${reviewId}/reopen`, wrap(unknownSchema), {}).then(r => r.data),
  },

  // ── Rewards ────────────────────────────────────────────────────────────────
  rewards: {
    evaluate: (event: { event_type: string; user_address: string; channel?: string; session_id?: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/rewards/evaluate', wrap(unknownSchema), event).then(r => r.data),

    listCampaigns: (params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/rewards/campaigns${buildQS({ ...params })}`, wrap(z.object({ campaigns: z.array(z.unknown()), count: z.number() }))).then(r => r.data),

    getCampaign: (campaignId: string) =>
      restClient.get(`/v1/rewards/campaigns/${campaignId}`, wrap(unknownSchema)).then(r => r.data),

    /** User reward history by wallet address — balances, earned, claimed, proofs. */
    userRewards: (address: string) =>
      restClient.get(`/v1/rewards/user/${address}`, wrap(unknownSchema)).then(r => r.data),

    /** Reward proof for on-chain claim. */
    getProof: (rewardId: string) =>
      restClient.get(`/v1/rewards/proof/${rewardId}`, wrap(unknownSchema)).then(r => r.data),

    queueStats: () =>
      restClient.get('/v1/rewards/queue/stats', wrap(unknownSchema)).then(r => r.data),

    // Decisions (eligibility verification results)
    listDecisions: (params?: { decision?: string; campaign_id?: string; limit?: number }) =>
      restClient.get(`/v1/rewards/decisions${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    getDecision: (decisionId: string) =>
      restClient.get(`/v1/rewards/decisions/${decisionId}`, wrap(unknownSchema)).then(r => r.data),

    // Actions (reward action payloads ready for tenant execution)
    listActions: (params?: { status?: string; rail?: string; limit?: number }) =>
      restClient.get(`/v1/rewards/actions${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    approveAction: (actionId: string) =>
      restClient.post(`/v1/rewards/actions/${actionId}/approve`, wrap(unknownSchema), {}).then(r => r.data),

    rejectAction: (actionId: string, reason: string) =>
      restClient.post(`/v1/rewards/actions/${actionId}/reject`, wrap(unknownSchema), { reason }).then(r => r.data),

    // Rails (delivery rail configuration)
    listRails: () =>
      restClient.get('/v1/rewards/rails', wrap(unknownSchema)).then(r => r.data),

    getRail: (railId: string) =>
      restClient.get(`/v1/rewards/rails/${railId}`, wrap(unknownSchema)).then(r => r.data),

    configureRail: (railId: string, config: Record<string, unknown>) =>
      restClient.put(`/v1/rewards/rails/${railId}`, wrap(unknownSchema), config).then(r => r.data),

    verifyRail: (railId: string) =>
      restClient.post(`/v1/rewards/rails/${railId}/verify`, wrap(unknownSchema), {}).then(r => r.data),

    // Reward campaigns (eligibility rule sets)
    createCampaign: (campaign: Record<string, unknown>) =>
      restClient.post('/v1/rewards/campaigns', wrap(unknownSchema), campaign).then(r => r.data),

    createCampaignRule: (campaignId: string, rule: Record<string, unknown>) =>
      restClient.post(`/v1/rewards/campaigns/${campaignId}/rules`, wrap(unknownSchema), rule).then(r => r.data),

    // Proofs (on-chain claim proofs)
    listProofs: (params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/rewards/proofs${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Attribution "Where" ───────────────────────────────────────────────────
  attribution: {
    /**
     * Resolve attribution for a specific conversion event.
     * Returns fractional credits per channel/source/campaign.
     * model defaults to 'multi_touch' if omitted.
     */
    resolve: (params: { user_id: string; event: Record<string, unknown>; model?: string; touchpoints?: unknown[] }) =>
      restClient.post('/v1/attribution/resolve', wrap(unknownSchema), params).then(r => r.data),

    recordTouchpoint: (tp: { user_id: string; channel: string; source: string; campaign?: string; event_type: string; timestamp: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/attribution/touchpoints', wrap(unknownSchema), tp).then(r => r.data),

    journey: (userId: string) =>
      restClient.get(`/v1/attribution/journey/${userId}`, wrap(unknownSchema)).then(r => r.data as AttributionJourney),

    clearJourney: (userId: string) =>
      restClient.delete(`/v1/attribution/journey/${userId}`, wrap(unknownSchema)),

    models: () =>
      restClient.get('/v1/attribution/models', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Web3 & On-Chain ────────────────────────────────────────────────────────
  web3: {
    chains: {
      list: (params?: { vm_family?: string; limit?: number }) =>
        restClient.get(`/v1/web3/chains${buildQS({ ...params })}`, wrap(z.object({ chains: z.array(unknownSchema), count: z.number() }))).then(r => r.data.chains),
      get: (chainId: string) =>
        restClient.get(`/v1/web3/chains/${chainId}`, wrap(unknownSchema)).then(r => r.data),
    },
    protocols: {
      list: (params?: { family?: string; chain?: string; q?: string; limit?: number }) =>
        restClient.get(`/v1/web3/protocols${buildQS({ ...params })}`, wrap(z.object({ protocols: z.array(unknownSchema), count: z.number() }))).then(r => r.data.protocols),
      get: (protocolId: string) =>
        restClient.get(`/v1/web3/protocols/${protocolId}`, wrap(unknownSchema)).then(r => r.data),
    },
    tokens: {
      list: (params?: { chain_id?: string; stablecoins?: boolean; limit?: number }) =>
        restClient.get(`/v1/web3/tokens${buildQS({ ...params })}`, wrap(z.object({ tokens: z.array(unknownSchema), count: z.number() }))).then(r => r.data.tokens),
    },
    contracts: {
      get: (chainId: string, address: string) =>
        restClient.get(`/v1/web3/contracts/${chainId}/${address}`, wrap(unknownSchema)).then(r => r.data),
    },
    domains: {
      get: (domain: string) =>
        restClient.get(`/v1/web3/domains/${encodeURIComponent(domain)}`, wrap(unknownSchema)).then(r => r.data),
    },
    governance: {
      listSpaces: (params?: { protocol_id?: string; limit?: number }) =>
        restClient.get(`/v1/web3/governance/spaces${buildQS({ ...params })}`, wrap(z.object({ spaces: z.array(unknownSchema), count: z.number() }))).then(r => r.data.spaces),
    },
    classify: {
      observation: (observation: Record<string, unknown>) =>
        restClient.post('/v1/web3/classify/observation', wrap(unknownSchema), observation).then(r => r.data),
    },
  },

  onchain: {
    /** On-chain actions for an agent — purchases, contract calls, transfers. */
    agentActions: (agentId: string) =>
      restClient.get(`/v1/onchain/actions/${agentId}`, wrap(z.object({ agent_id: z.string(), actions: z.array(unknownSchema), count: z.number() }))).then(r => r.data.actions),

    /** Contract metadata — ABI classification, protocol mapping, risk flags. */
    getContract: (address: string) =>
      restClient.get(`/v1/onchain/contracts/${address}`, wrap(unknownSchema)).then(r => r.data),

    rpcHealth: () =>
      restClient.get('/v1/onchain/rpc/health', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Oracle (proof generation / verification) ───────────────────────────────
  oracle: {
    generateProof: (params: { user: string; action_type: string; amount_wei: number }) =>
      restClient.post('/v1/oracle/proof/generate', wrap(z.object({
        user: z.string(), action_type: z.string(), amount_wei: z.number(),
        nonce: z.string(), expiry: z.number(), chain_id: z.number(),
        contract_address: z.string(), signature: z.string(), message_hash: z.string(),
      }).passthrough()), params).then(r => r.data),

    verifyProof: (params: { user: string; action_type: string; amount_wei: number; nonce: string; expiry: number; chain_id: number; contract_address: string; signature: string; message_hash: string }) =>
      restClient.post('/v1/oracle/proof/verify', wrap(z.object({
        verified: z.boolean(), verified_at: z.string().optional(),
      }).passthrough()), params).then(r => r.data),
  },

  // ── x402 (HTTP payment tracking) ──────────────────────────────────────────
  x402: {
    capture: (transaction: Record<string, unknown>) =>
      restClient.post('/v1/x402/capture', wrap(unknownSchema), transaction).then(r => r.data),

    agentHistory: (agentId: string) =>
      restClient.get(`/v1/x402/agent/${agentId}`, wrap(unknownSchema)).then(r => r.data),

    graph: () =>
      restClient.get('/v1/x402/graph', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Flows (wallet linking, transfers, assets) ──────────────────────────────
  flows: {
    wallets: {
      list: (entityId: string, limit = 50) =>
        restClient.get(`/v1/flows/wallets${buildQS({ entity_id: entityId, limit })}`, wrap(z.object({ entity_id: z.string(), wallets: z.array(unknownSchema), count: z.number() }))).then(r => r.data.wallets),
      link: (wallet: { owner_entity_id: string; chain: string; address: string }) =>
        restClient.post('/v1/flows/wallets', wrap(unknownSchema), wallet).then(r => r.data),
    },
    transfers: {
      list: (entityId: string, limit = 50) =>
        restClient.get(`/v1/flows/transfers${buildQS({ entity_id: entityId, limit })}`, wrap(z.object({ entity_id: z.string(), transfers: z.array(unknownSchema), count: z.number() }))).then(r => r.data.transfers),
      record: (transfer: { from_entity_id: string; to_entity_id: string; asset_id: string; amount: number; [k: string]: unknown }) =>
        restClient.post('/v1/flows/transfers', wrap(unknownSchema), transfer).then(r => r.data),
    },
    assets: {
      get: (assetId: string) =>
        restClient.get(`/v1/flows/assets/${assetId}`, wrap(unknownSchema)).then(r => r.data),
    },
  },

  // ── Intelligence (wallet risk + entity cluster) ────────────────────────────
  intelligence: {
    walletRisk: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/risk`, wrap(unknownSchema)).then(r => r.data as WalletRiskProfile),

    walletProfile: (address: string) =>
      restClient.get(`/v1/intelligence/wallet/${address}/profile`, wrap(unknownSchema)).then(r => r.data as Web3WalletProfile),

    entityCluster: (entityId: string) =>
      restClient.get(`/v1/intelligence/entity/${entityId}/cluster`, wrap(unknownSchema)).then(r => r.data as EntityCluster),

    recommendations: (params?: { family?: string }) =>
      restClient.get(`/v1/intelligence/recommendations${buildQS({ recommendation_type: params?.family })}`, wrap(unknownSchema)).then(r => r.data),

    recommendationInvestigation: (recommendationId: string) =>
      restClient.get(`/v1/intelligence/recommendations/${recommendationId}/investigation`, wrap(unknownSchema)).then(r => r.data),

    outcomeLedger: () =>
      restClient.get(`/v1/intelligence/outcome-ledger`, wrap(unknownSchema)).then(r => r.data),

    outcomeLedgerSummary: () =>
      restClient.get(`/v1/intelligence/outcome-ledger/summary`, wrap(unknownSchema)).then(r => r.data),

    outcomes: () =>
      restClient.get(`/v1/intelligence/outcomes`, wrap(unknownSchema)).then(r => r.data),

    playbooks: () =>
      restClient.get(`/v1/intelligence/playbooks`, wrap(unknownSchema)).then(r => r.data),

    playbookTemplates: () =>
      restClient.get(`/v1/intelligence/playbooks/templates`, wrap(unknownSchema)).then(r => r.data),

    createPlaybookFromTemplate: (templateId: string) =>
      restClient.post(`/v1/intelligence/playbooks/from-template`, wrap(unknownSchema), { template_id: templateId }).then(r => r.data),

    playbookRuns: (playbookId: string) =>
      restClient.get(`/v1/intelligence/playbooks/${playbookId}/runs`, wrap(unknownSchema)).then(r => r.data),

    playbookPerformance: (playbookId: string) =>
      restClient.get(`/v1/intelligence/playbooks/${playbookId}/performance`, wrap(unknownSchema)).then(r => r.data),

    playbookPerformanceSummary: () =>
      restClient.get(`/v1/intelligence/playbooks/performance/summary`, wrap(unknownSchema)).then(r => r.data),

    auditExportTypes: () =>
      restClient.get('/v1/intelligence/audit-exports/types', wrap(unknownSchema)).then(r => r.data),

    createAuditExport: (payload: Record<string, unknown>) =>
      restClient.post('/v1/intelligence/audit-exports', wrap(unknownSchema), payload).then(r => r.data),

    auditExport: (exportId: string) =>
      restClient.get(`/v1/intelligence/audit-exports/${exportId}`, wrap(unknownSchema)).then(r => r.data),

    downloadAuditExport: (exportId: string) =>
      restClient.get(`/v1/intelligence/audit-exports/${exportId}/download`, wrap(unknownSchema)).then(r => r.data),

    accountHealth: (entityId?: string, params?: { window?: string }) =>
      restClient.get(`/v1/intelligence/account-health${buildQS({ entity_id: entityId, ...params })}`, wrap(unknownSchema)).then(r => r.data),

    revenueIntelligence: (entityId?: string, params?: { window?: string }) =>
      restClient.get(`/v1/intelligence/revenue-intelligence${buildQS({ entity_id: entityId, ...params })}`, wrap(unknownSchema)).then(r => r.data),

    experienceIntelligence: (entityId?: string, params?: { window?: string }) =>
      restClient.get(`/v1/intelligence/experience-intelligence${buildQS({ entity_id: entityId, ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Analytics ─────────────────────────────────────────────────────────────
  analytics: {
    dashboardSummary: () =>
      restClient.get('/v1/analytics/dashboard/summary', wrap(unknownSchema)).then(r => r.data),

    queryEvents: (query: { event_type?: string; start_date?: string; end_date?: string; user_id?: string; session_id?: string; limit?: number }) =>
      restClient.post('/v1/analytics/events/query', wrap(z.object({
        data: z.array(z.unknown()),
        pagination: z.object({ total: z.number(), limit: z.number(), has_more: z.boolean() }).optional(),
      }).passthrough()), query).then(r => r.data),

    graphql: (query: string, variables?: Record<string, unknown>) =>
      restClient.post('/v1/analytics/graphql', wrap(z.object({
        data: z.unknown().nullable(),
        errors: z.array(z.object({ message: z.string() }).passthrough()).optional().nullable(),
      })), { query, variables }).then(r => r.data),

    export: (params: { format?: 'csv' | 'json' | 'parquet'; query?: { event_type?: string; start_date?: string; end_date?: string; user_id?: string; session_id?: string; limit?: number } }) =>
      restClient.post('/v1/analytics/export', wrap(z.object({ export_id: z.string(), status: z.string() })), params).then(r => r.data),

    exportStatus: (exportId: string) =>
      restClient.get(`/v1/analytics/export/${exportId}`, wrap(z.object({ export_id: z.string(), status: z.string(), download_url: z.string().optional() }))).then(r => r.data),
  },

  // ── Automation (campaign metrics + platform overview) ──────────────────────
  automation: {
    metrics: (campaignId: string, hours = 24) =>
      restClient.get(`/v1/automation/metrics/${campaignId}?hours=${hours}`, wrap(unknownSchema)).then(r => r.data),

    overview: (hours = 24) =>
      restClient.get(`/v1/automation/overview?hours=${hours}`, wrap(unknownSchema)).then(r => r.data),

    insights: () =>
      restClient.get('/v1/automation/insights', wrap(unknownSchema)).then(r => r.data),

    ingest: (event: { type: string; campaign_id?: string; user?: Record<string, unknown>; wallet_address?: string; timestamp?: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/automation/ingest', wrap(unknownSchema), event).then(r => r.data),
  },

  // ── Providers (tenant-safe subset) ────────────────────────────────────────
  providers: {
    health: () =>
      restClient.get('/v1/providers/health', wrap(unknownSchema)).then(r => r.data),

    categories: () =>
      restClient.get('/v1/providers/categories', wrap(unknownSchema)).then(r => r.data),
  },

  // ── Ingestion (SDK event capture) ─────────────────────────────────────────
  ingest: {
    event: (event: { event_type: string; session_id: string; properties?: Record<string, unknown>; timestamp?: string; user_id?: string; device_id?: string }) =>
      restClient.post('/v1/ingest/events', wrap(unknownSchema), event).then(r => r.data),

    batch: (events: unknown[]) =>
      restClient.post('/v1/ingest/events/batch', wrap(unknownSchema), { events }).then(r => r.data),

    feed: (feed: { source: string; entity_type: string; data: Record<string, unknown> }) =>
      restClient.post('/v1/ingest/feed', wrap(unknownSchema), feed).then(r => r.data),
  },

  // ── Entities (user/agent listing + search for tenant scope) ──────────────
  entities: {
    /** List entities scoped to this tenant. type='user' returns all tracked users. */
    list: (params?: { type?: string; limit?: number; offset?: number; order_by?: string }) =>
      restClient.get(`/v1/entities${buildQS({ ...params })}`, wrap(z.object({ entities: z.array(z.unknown()), total: z.number() }))).then(r => r.data),

    /** Full-text search across entity fields — name, email, wallet address, device ID. */
    search: (q: string, type?: string, limit = 50) =>
      restClient.get(`/v1/entities/search${buildQS({ q, type, limit })}`, wrap(z.object({ results: z.array(z.unknown()), total: z.number() }))).then(r => r.data),

    /** Single entity summary. */
    get: (entityId: string) =>
      restClient.get(`/v1/entities/${entityId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Realtime (SSE / WebSocket URLs) ───────────────────────────────────────
  realtime: {
    sseUrl: (entityId?: string) =>
      `/v1/realtime/sse${entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ''}` as string,
    wsUrl: (entityId?: string) =>
      `/v1/realtime/ws${entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ''}` as string,
    wsSubscribeUrl: () => '/v1/realtime/ws/subscribe' as string,
  },

  // ── Graph Intelligence (GraphTraversalEngine-backed routes) ───────────────
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

    query: (body: Record<string, unknown>) =>
      restClient.post('/v1/graph/query', unknownSchema, body),

    paths: (body: import('@aether/shared/operational-intelligence').PathQuery) =>
      restClient.post('/v1/graph/paths', unknownSchema, body),

    expand: (body: import('@aether/shared/operational-intelligence').NodeExpansionRequest) =>
      restClient.post('/v1/graph/paths/expand', unknownSchema, body),

    explain: (body: { tenant_id: string; path_id: string }) =>
      restClient.post('/v1/graph/paths/explain', unknownSchema, body),

    createSnapshot: (body: {
      tenant_id: string;
      query?: Record<string, unknown>;
      path_ids?: string[];
      node_ids?: string[];
      edge_ids?: string[];
      graph_watermark?: string;
    }) => restClient.post('/v1/graph/snapshots', unknownSchema, body),

    getSnapshot: (id: string, tenant_id: string) =>
      restClient.get(`/v1/graph/snapshots/${id}?tenant_id=${encodeURIComponent(tenant_id)}`, unknownSchema),

    compareSnapshot: (id: string, body: { tenantId: string; anchor: unknown; asOf: string; compareTo: string }) =>
      restClient.post(`/v1/graph/snapshots/${id}/compare`, unknownSchema, body),

    createJob: (body: import('@aether/shared/operational-intelligence').PathQuery) =>
      restClient.post('/v1/graph/paths/jobs', unknownSchema, body),

    getJob: (jobId: string, tenant_id: string) =>
      restClient.get(`/v1/graph/paths/jobs/${jobId}?tenant_id=${encodeURIComponent(tenant_id)}`, unknownSchema),
  },

  // ── Cluster360 ─────────────────────────────────────────────────────────────
  clusters: {
    get: (clusterId: string, params?: { tenant_id?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
    members: (clusterId: string, params?: { tenant_id?: string; limit?: number; cursor?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}/members${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
    timeline: (clusterId: string, params?: { tenant_id?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}/timeline${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
    economic: (clusterId: string, params?: { tenant_id?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}/economic${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
    campaigns: (clusterId: string, params?: { tenant_id?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}/campaigns${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
    risk: (clusterId: string, params?: { tenant_id?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}/risk${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
    geography: (clusterId: string, params?: { tenant_id?: string }) =>
      restClient.get(`/v1/clusters/${clusterId}/geography${buildQS({ ...(params ?? {}) })}`, wrap(unknownSchema)).then(r => r.data),
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

  // ── Investigations (case management) ──────────────────────────────────────
  investigations: {
    create: (body: {
      tenantId: string;
      title: string;
      subjects?: Array<{ kind: string; id: string }>;
      createdBy: string;
    }) => restClient.post('/v1/investigations', unknownSchema, body),

    list: (tenantId: string, status?: string, limit = 50) =>
      restClient.get(`/v1/investigations${buildQS({ tenantId, status, limit })}`, unknownSchema),

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

  // ── Governance (policy decisions + audit) ─────────────────────────────────
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

    audit: (tenantId: string, limit = 100, principal_id?: string) =>
      restClient.get(`/v1/governance/audit${buildQS({ tenantId, limit, principal_id })}`, unknownSchema),
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

  // ── Notifications (webhooks + alert rules — legacy) ──────────────────────
  notifications: {
    /** List all webhook configs for this tenant. */
    webhooks: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/notifications/webhooks${buildQS({ tenant_id: tenantId, limit })}`, wrap(webhookPageSchema)).then(r => r.data),

    /** Register a new webhook; the signing secret is returned only once. */
    createWebhook: (body: { url: string; events: string[]; secret?: string; active?: boolean }) =>
      restClient.post('/v1/notifications/webhooks', wrap(customerWebhookCreateResponseSchema), body).then(r => r.data),

    /** List all alert rules for this tenant. */
    alerts: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/notifications/alerts${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Delete a webhook config. */
    deleteWebhook: (webhookId: string) =>
      restClient.delete(`/v1/notifications/webhooks/${webhookId}`, wrap(z.object({ deleted: z.boolean() }))).then(r => r.data),

    /** Send a test ping to a webhook endpoint. */
    testWebhook: (webhookId: string) =>
      restClient.post(`/v1/notifications/webhooks/${webhookId}/test`, wrap(webhookTestResultSchema), {}).then(r => r.data),

    /** Create a new alert rule. */
    createAlert: (body: Record<string, unknown>) =>
      restClient.post('/v1/notifications/alerts', wrap(unknownSchema), body).then(r => r.data),
  },

  // ── Notification Intelligence Channels ────────────────────────────────────
  notificationChannels: {
    /** List all notification channels for the authenticated tenant. */
    list: () =>
      restClient.get('/v1/notifications/channels', wrap(unknownSchema)).then(r => r.data as unknown[]),

    /** Register a new channel (Discord, Telegram, Webhook). */
    register: (body: {
      channel_type: string;
      channel_name?: string;
      channel_config?: Record<string, unknown>;
      severity_filter?: string[];
    }) =>
      restClient.post('/v1/notifications/channels', wrap(unknownSchema), body).then(r => r.data),

    /** Update a channel's filter/name. */
    update: (channelId: string, body: { severity_filter?: string[]; active?: boolean; channel_name?: string }) =>
      restClient.patch(`/v1/notifications/channels/${channelId}`, wrap(unknownSchema), body).then(r => r.data),

    /** Delete a channel. */
    remove: (channelId: string) =>
      restClient.delete(`/v1/notifications/channels/${channelId}`, wrap(unknownSchema)).then(r => r.data),

    /** Send a test message to verify a channel. */
    test: (channelId: string) =>
      restClient.post(`/v1/notifications/channels/${channelId}/test`, wrap(unknownSchema), {}).then(r => r.data),

    /** Start Slack OAuth flow. Returns { redirect_url }. */
    slackConnect: () =>
      restClient.get('/v1/notifications/channels/slack/connect', wrap(unknownSchema)).then(r => r.data as { redirect_url?: string }),

    /** Get tenant notification config (channel map, rate limits, etc). */
    getConfig: (tenantId: string) =>
      restClient.get(`/v1/notifications/config${buildQS({ tenantId })}`, wrap(unknownSchema)).then(r => r.data),

    /** Update tenant notification config (channel map, Slack bot token, etc). */
    updateConfig: (tenantId: string, body: {
      slack_bot_token?: string;
      slack_channel_map?: Record<string, string>;
      rate_limit_per_minute?: number;
      operator_review_required?: string[];
      quiet_hours?: { start?: string; end?: string; timezone?: string };
      timezone?: string;
      digest?: { enabled?: boolean; frequency?: string; send_time?: string };
    }) =>
      restClient.put(`/v1/notifications/config${buildQS({ tenantId })}`, wrap(unknownSchema), body).then(r => r.data),
  },

  // ── Tenant In-App Notification Inbox ──────────────────────────────────────
  inbox: {
    /** List the authenticated tenant's in-app inbox notifications (newest first). */
    list: (params?: { unread?: boolean; include_archived?: boolean; limit?: number; offset?: number }) =>
      restClient.get(`/v1/notifications/inbox${buildQS({ ...params })}`, wrap(z.array(z.unknown()))).then(r => r.data as Record<string, unknown>[]),

    /** Unread (non-archived) inbox notification count. */
    unreadCount: () =>
      restClient.get('/v1/notifications/inbox/unread-count', wrap(z.object({ unread: z.number() }))).then(r => r.data),

    /** Mark one inbox notification read (idempotent). */
    markRead: (notificationId: string) =>
      restClient.post(`/v1/notifications/inbox/${encodeURIComponent(notificationId)}/read`, wrap(unknownSchema), {}).then(r => r.data),

    /** Mark every unread inbox notification read. */
    markAllRead: () =>
      restClient.post('/v1/notifications/inbox/read-all', wrap(z.object({ read: z.number() })), {}).then(r => r.data),

    /** Archive one inbox notification (idempotent). */
    archive: (notificationId: string) =>
      restClient.post(`/v1/notifications/inbox/${encodeURIComponent(notificationId)}/archive`, wrap(unknownSchema), {}).then(r => r.data),
  },

  // ── Behavior Profile (read-side snapshots) ────────────────────────────────
  behavior: {
    /** Latest behavior snapshot for an entity. */
    profile: (entityId: string) =>
      restClient.get(`/v1/behavior/${entityId}`, wrap(unknownSchema)).then(r => r.data),

    /** Historical behavior snapshots. */
    history: (entityId: string, window = '7d', limit = 50) =>
      restClient.get(`/v1/behavior/${entityId}/history${buildQS({ window, limit })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Population Intelligence (macro / meso / micro) ────────────────────────
  population: {
    /** Macro overview: group counts by type, total tracked memberships, top groups. */
    summary: (tenantId: string) =>
      restClient.get(`/v1/population/summary${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),

    /** List all population groups, optionally filtered by type. */
    groups: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/population/groups${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Create a new population group (segment, cohort, cluster, community, etc.). */
    createGroup: (body: Record<string, unknown>) =>
      restClient.post('/v1/population/groups', wrap(unknownSchema), body).then(r => r.data),

    /** Get group details including definition, metadata, and member count. */
    group: (id: string, tenantId: string) =>
      restClient.get(`/v1/population/groups/${id}${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),

    /** List members of a group with confidence and membership evidence. */
    groupMembers: (id: string, tenantId: string, limit = 50) =>
      restClient.get(`/v1/population/groups/${id}/members${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Get all groups an entity belongs to with confidence and basis. */
    entityMemberships: (entityId: string, tenantId: string) =>
      restClient.get(`/v1/population/entity/${entityId}/memberships${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Agent Tasks ───────────────────────────────────────────────────────────
  agent: {
    /** List recent agent tasks for this tenant. */
    tasks: (tenantId: string, status?: string, limit = 50) =>
      restClient.get(`/v1/agent/tasks${buildQS({ tenant_id: tenantId, status, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Submit a new task to the agent controller. */
    createTask: (body: Record<string, unknown>) =>
      restClient.post('/v1/agent/tasks', wrap(unknownSchema), body).then(r => r.data),

    /** Get task status and result. */
    task: (taskId: string) =>
      restClient.get(`/v1/agent/tasks/${taskId}`, wrap(unknownSchema)).then(r => r.data),

    /** Record a task lifecycle event (started, tool_called, decision_made, completed, verified). */
    taskLifecycle: (taskId: string, body: Record<string, unknown>) =>
      restClient.post(`/v1/agent/tasks/${taskId}/lifecycle`, wrap(unknownSchema), body).then(r => r.data),
  },

  // ── RWA Intelligence ──────────────────────────────────────────────────────
  rwa: {
    /** List registered RWA assets for this tenant. */
    assets: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/rwa/assets${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Register a tokenized real-world asset as an intelligence object. */
    createAsset: (body: Record<string, unknown>) =>
      restClient.post('/v1/rwa/assets', wrap(unknownSchema), body).then(r => r.data),

    /** Get full asset details. */
    asset: (id: string) =>
      restClient.get(`/v1/rwa/assets/${id}`, wrap(unknownSchema)).then(r => r.data),

    /** Get RWA exposure for an entity across all assets. */
    exposure: (entityId: string) =>
      restClient.get(`/v1/rwa/exposure/${entityId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Delegations ───────────────────────────────────────────────────────────
  delegations: {
    /** List delegations for this tenant (filterable by grantor, grantee, active). */
    list: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/delegations${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Grant a new delegation. */
    create: (body: Record<string, unknown>) =>
      restClient.post('/v1/delegations', wrap(unknownSchema), body).then(r => r.data),

    /** Read a single delegation by ID. */
    get: (id: string, tenantId: string) =>
      restClient.get(`/v1/delegations/${id}${buildQS({ tenant_id: tenantId })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Commerce ──────────────────────────────────────────────────────────────
  commerce: {
    /** Record a commerce payment between entities. */
    recordPayment: (payment: Record<string, unknown>) =>
      restClient.post('/v1/commerce/payments', wrap(unknownSchema), payment).then(r => r.data),

    /** Record an agent hire transaction. */
    recordHire: (hire: Record<string, unknown>) =>
      restClient.post('/v1/commerce/hires', wrap(unknownSchema), hire).then(r => r.data),

    /** Fee report for a given period. */
    feesReport: (period?: string) =>
      restClient.get(`/v1/commerce/fees/report${period ? `?period=${period}` : ''}`, wrap(unknownSchema)).then(r => r.data),

    /** Commerce spend breakdown for an agent. */
    agentSpend: (agentId: string) =>
      restClient.get(`/v1/commerce/agent/${agentId}/spend`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Customer auth (email registration + OTP + SSO callback) ─────────────
  // Under the trust-plane posture (backend HUMAN_SESSIONS_ENABLED) these
  // endpoints return a durable `session` grant instead of a reusable
  // `api_key`; both shapes are typed so the app can prefer sessions and fall
  // back to the legacy key only when the flag is off.
  auth: {
    /**
     * Local-only backend development identity. The backend owns and persists
     * the session; the browser never manufactures a credential.
     */
    developmentSession: () =>
      restClient.post('/v1/auth/development-session', wrap(unknownSchema), {})
        .then(r => r.data as AuthGrantResponse & { tenant_id: string }),

    /** Step 1: register email+password → sends 6-digit OTP. */
    register: (body: { name: string; email: string; password: string; plan_tier: string }) =>
      restClient.post('/v1/auth/register', wrap(unknownSchema), body).then(r => r.data),

    /** Step 2: verify OTP code — creates tenant + returns a session (or legacy API key). */
    verifyEmail: (email: string, code: string) =>
      restClient.post('/v1/auth/verify-email', wrap(unknownSchema), { email, code })
        .then(r => r.data as AuthGrantResponse & { tenant_id: string; name?: string }),

    /** Email + password login for returning users. */
    login: (email: string, password: string) =>
      restClient.post('/v1/auth/login', wrap(unknownSchema), { email, password })
        .then(r => r.data as AuthGrantResponse & { tenant_id: string }),

    /** Exchange Auth0 JWT for an Aether session (or legacy API key) — SSO callback. */
    ssoCallback: (jwt: string) =>
      restClient.post('/v1/auth/sso/callback', wrap(unknownSchema), { jwt })
        .then(r => r.data as AuthGrantResponse),
  },

  // ── Self-service account (me) ──────────────────────────────────────────────
  me: {
    /** Authenticated tenant profile, plan, and billing. */
    profile: () =>
      restClient.get('/v1/me', wrap(unknownSchema)).then(r => r.data as {
        tenant_id: string;
        name: string;
        contact_email: string;
        plan: { plan_id: string; display_name: string; monthly_quota: number; burst_rpm: number };
        billing: { subscription_status?: string; current_period_end?: string | null };
        api_key_count: number;
        is_admin: boolean;
      }),

    /** Current-period event and RPM usage. */
    usage: () =>
      restClient.get('/v1/me/usage', wrap(unknownSchema)).then(r => r.data as {
        period_start: string;
        period_end: string;
        events_used: number;
        events_quota: number;
        rpm_peak: number;
        rpm_limit: number;
        overage_events: number;
        days_remaining: number;
      }),

    /** Begin the durable 30-day account-deletion recovery workflow. */
    deleteAccount: (body: { idempotency_key: string; reauth_evidence: {
      verified: true;
      method: 'password' | 'mfa' | 'webauthn' | 'identity_provider';
      evidence_id: string;
      verified_at: string;
      assurance_level: 'step_up' | 'high' | 'aal2' | 'aal3';
      provider?: string;
    } }) =>
      restClient.post('/v1/account-lifecycle/deletion', wrap(deletionWorkflowSchema), body).then(r => r.data),

    /** Read a previously requested deletion workflow. */
    deletionStatus: (workflowId: string) =>
      restClient.get(`/v1/account-lifecycle/deletion/${encodeURIComponent(workflowId)}`, wrap(deletionWorkflowSchema)).then(r => r.data),

    /** Cancel deletion while the 30-day recovery window is open. */
    cancelDeletion: (workflowId: string, reauth_evidence: {
      verified: true;
      method: 'password' | 'mfa' | 'webauthn' | 'identity_provider';
      evidence_id: string;
      verified_at: string;
      assurance_level: 'step_up' | 'high' | 'aal2' | 'aal3';
      provider?: string;
    }) =>
      restClient.post(`/v1/account-lifecycle/deletion/${encodeURIComponent(workflowId)}/cancel`, wrap(deletionWorkflowSchema), { reauth_evidence }).then(r => r.data),

    /** Durable human sessions for the authenticated tenant (no token hashes). */
    sessions: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/me/sessions${buildQS({ ...params })}`, wrap(z.object({
        sessions: z.array(z.unknown()),
        count: z.number(),
        total: z.number(),
        limit: z.number(),
        offset: z.number(),
      }))).then(r => r.data as {
        sessions: Record<string, unknown>[];
        count: number;
        total: number;
        limit: number;
        offset: number;
      }),

    /** Revoke one tenant-owned session. */
    revokeSession: (sessionId: string) =>
      restClient.delete(`/v1/me/sessions/${encodeURIComponent(sessionId)}`, wrap(z.object({ revoked: z.boolean(), id: z.string() }))).then(r => r.data),

    /** Revoke every session except the caller's current one. */
    revokeOtherSessions: () =>
      restClient.post('/v1/me/sessions/revoke-others', wrap(z.object({ revoked_count: z.number() })), {}).then(r => r.data),
  },

  // ── Organization management (tenant-scoped) ──────────────────────────────
  organization: {
    profile: () =>
      restClient.get('/v1/account/organization/profile', wrap(organizationProfileSchema)).then(r => r.data),
    updateProfile: (body: { name?: string; slug?: string; description?: string | null }) =>
      restClient.patch('/v1/account/organization/profile', wrap(organizationProfileSchema), body).then(r => r.data),
    members: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/account/organization/members${buildQS({ ...params })}`, z.object({
        data: z.array(organizationMemberSchema),
        pagination: paginationSchema,
        meta: z.object({ request_id: z.string(), timestamp: z.string() }),
      })),
    invitations: () =>
      restClient.get('/v1/account/organization/invitations', wrap(z.array(organizationInvitationSchema))).then(r => r.data),
    invite: (body: { email: string; role?: 'admin' | 'member' | 'viewer'; expires_in_hours?: number }) =>
      restClient.post('/v1/account/organization/invitations', wrap(organizationInvitationSchema.extend({ token: z.string() })), body).then(r => r.data),
    revokeInvitation: (invitationId: string) =>
      restClient.post(`/v1/account/organization/invitations/${encodeURIComponent(invitationId)}/revoke`, wrap(organizationInvitationSchema)).then(r => r.data),
    changeMemberRole: (memberId: string, role: 'owner' | 'admin' | 'member' | 'viewer') =>
      restClient.patch(`/v1/account/organization/members/${encodeURIComponent(memberId)}/role`, wrap(organizationMemberSchema), { role }).then(r => r.data),
    removeMember: (memberId: string) =>
      restClient.delete(`/v1/account/organization/members/${encodeURIComponent(memberId)}`, wrap(z.object({ member_id: z.string(), removed: z.boolean() }))).then(r => r.data),
  },

  // ── API key management ─────────────────────────────────────────────────────
  settings: {
    listKeys: () =>
      restClient.get('/v1/me/api-keys', wrap(z.object({
        tenant_id: z.string(),
        api_keys: z.array(apiKeySchema),
        count: z.number(),
        total: z.number(),
        limit: z.number(),
        offset: z.number(),
      }))).then(r => r.data),

    createKey: (payload: { name: string; tier?: string; permissions?: string[]; platform?: string | null }) =>
      restClient.post('/v1/me/api-keys', wrap(unknownSchema), payload)
        .then(r => r.data as { id: string; name: string; key: string; api_key: string; tier: string; permissions: string[]; platform: string | null }),

    revokeKey: (id: string) =>
      restClient.delete(`/v1/me/api-keys/${id}`, wrap(unknownSchema)),
  },

  // ── SDK fleet health & remote config (tenant-scoped) ────────────────────────
  sdk: {
    /** Fleet health summary for the caller's tenant. */
    fleet: () =>
      restClient.get('/v1/diagnostics/sdk/health', wrap(unknownSchema)).then(r => r.data),
    /** Health score for a single SDK instance. */
    sdkScore: (sdkId: string) =>
      restClient.get(`/v1/diagnostics/sdk/health/${encodeURIComponent(sdkId)}`, wrap(unknownSchema)).then(r => r.data),
    /** SDK instances that have gone silent (no heartbeat within threshold). */
    silent: () =>
      restClient.get('/v1/diagnostics/sdk/silent', wrap(unknownSchema)).then(r => r.data),
    /**
     * Active remote-config manifest for the tenant (admin, ungated).
     * Uses the management endpoint that bypasses SDK cohort/rollout gating so
     * the settings UI always reflects the latest published manifest.
     */
    manifest: () =>
      restClient.get('/v1/config/sdk/manifest/active', wrap(unknownSchema)).then(r => r.data),
    /** Publish a new manifest version (requires admin permission). */
    publishManifest: (body: Record<string, unknown>) =>
      restClient.put('/v1/config/sdk/manifest', wrap(unknownSchema), body).then(r => r.data),
    /** Rollout adoption status + manifest versioning metadata (admin). */
    rolloutStatus: () =>
      restClient.get('/v1/config/sdk/rollout', wrap(unknownSchema)).then(r => r.data),
    /** Roll back to the previous manifest version (admin). */
    rollback: () =>
      restClient.post('/v1/config/sdk/rollout/rollback', wrap(unknownSchema), {}).then(r => r.data),
  },

  // ── Billing & plans ────────────────────────────────────────────────────────
  billing: {
    capability: () =>
      restClient.get('/v1/billing/capability', wrap(z.object({
        provider: z.literal('stripe'),
        status: z.enum(['not_configured', 'degraded', 'available']),
        enabled: z.boolean(),
        required: z.boolean(),
        detail: z.string(),
      }))).then(r => r.data),

    plans: () =>
      restClient.get('/v1/billing/plans', wrap(z.object({ plans: z.array(billingPlanSchema) })))
        .then(r => r.data),

    createCheckout: (planTier: string) =>
      restClient.post('/v1/billing/checkout', wrap(z.object({
        session_id: z.string(),
        url: z.string().url(),
      })), { plan_tier: planTier }).then(r => r.data),

    portal: () =>
      restClient.post('/v1/billing/portal', wrap(unknownSchema))
        .then(r => r.data as { url: string | null }),

    invoices: () =>
      restClient.get('/v1/billing/invoices', wrap(z.object({
        tenant_id: z.string(),
        invoices: z.array(invoiceSchema),
        count: z.number(),
      }))).then(r => r.data),

    plan: () =>
      restClient.get('/v1/billing/plan', wrap(unknownSchema)).then(r => r.data),

    entitlements: () =>
      restClient.get('/v1/billing/entitlements', wrap(unknownSchema)).then(r => r.data),

    usageSummary: () =>
      restClient.get('/v1/billing/usage/summary', wrap(unknownSchema)).then(r => r.data),

    invoicePreviews: () =>
      restClient.get('/v1/billing/invoice-previews', wrap(unknownSchema)).then(r => r.data),

    valueCreated: () =>
      restClient.get('/v1/billing/value-created', wrap(unknownSchema)).then(r => r.data),


  },

  // ── Enterprise contact ─────────────────────────────────────────────────────
  contact: {
    enterprise: (payload: { name: string; email: string; company_name: string; company_type: 'startup' | 'smb' | 'enterprise' | 'government' | 'nonprofit'; message: string }) =>
      restClient.post('/v1/contact/enterprise', wrap(unknownSchema), payload).then(r => r.data),
  },

  // ── Social Intelligence (12-platform unified grid) ─────────────────────────
  social: {
    /** Unified social intelligence for a user — all 12 platforms in one response. */
    intelligence: (userId: string, window = '30d') =>
      restClient.get(`/v1/profile/${userId}/social-intelligence${buildQS({ window })}`, wrap(unknownSchema))
        .then(r => r.data as {
          influence_level: 'high' | 'medium' | 'low' | null;
          total_followers_deduped: number | null;
          platforms: Array<{
            platform: string;
            handle: string | null;
            followers: number | null;
            verified: boolean;
            engagement_rate: number | null;
            content_count: number | null;
            extra: Record<string, unknown>;
          }>;
          computed_at: string | null;
        }),
  },

  // ── Geographic Intelligence ─────────────────────────────────────────────────
  geo: {
    /** Aggregate geographic summary for the tenant's entity pool at a given level. */
    summary: (params?: { level?: string; geo_id?: string; window?: string }) =>
      restClient.get(`/v1/geo/summary${buildQS({ ...params })}`, wrap(unknownSchema))
        .then(r => r.data as {
          level: string;
          geo_id: string | null;
          geo_name: string | null;
          entity_count: number;
          tier_distribution: Record<string, number>;
          avg_edges_per_entity: number | null;
          conversion_rate: number | null;
          anomaly_flags: number;
          children: Array<{
            geo_id: string;
            geo_name: string;
            entity_count: number;
            conversion_rate: number | null;
            anomaly_flags: number;
          }>;
          computed_at: string | null;
        }),

    /** Entities at a specific geographic location, paginated. */
    entities: (params: { level: string; geo_id: string; window?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/geo/entities${buildQS({ ...params })}`, wrap(unknownSchema))
        .then(r => r.data as {
          entities: Array<{
            entity_id: string;
            display_name: string | null;
            tier: string | null;
            ltv: number | null;
            risk_score: number | null;
            last_active_at: string | null;
          }>;
          total: number;
        }),
  },

  // ── Recommendations (pending retarget / campaign actions) ──────────────────
  recommendations: {
    /** Pending recommendation cards for a user requiring analyst approval.
     *  Backend returns: { data: { entity_id, kind, items: [...], pagination, provenance } }
     *  We normalise to { items: [...] } so callers can filter on status directly. */
    forUser: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/retarget-recommendations`, wrap(unknownSchema))
        .then(r => {
          const envelope = r.data as { items?: unknown[] } | null;
          const items = (envelope?.items ?? []) as Array<{
            id: string;
            platform: string;
            action: string;
            creative_theme: string | null;
            estimated_bid: number | null;
            confidence: number;
            reasoning: string[];
            status: 'pending_review' | 'approved' | 'rejected' | 'executing' | 'executed' | 'failed';
          }>;
          return { items };
        }),

    /** Approve a recommendation — requires human confirmation before calling.
     *  Backend: POST /v1/recommendations/{id}/approve  body: { reviewed_by, review_notes? } */
    approve: (recommendationId: string, reviewedBy: string, reviewNotes?: string) =>
      restClient.post(`/v1/recommendations/${recommendationId}/approve`, wrap(unknownSchema), {
        reviewed_by: reviewedBy,
        review_notes: reviewNotes ?? null,
      }).then(r => r.data),

    /** Reject a recommendation.
     *  Backend: POST /v1/recommendations/{id}/reject  body: { reviewed_by, reason } */
    reject: (recommendationId: string, reviewedBy: string, reason: string) =>
      restClient.post(`/v1/recommendations/${recommendationId}/reject`, wrap(unknownSchema), {
        reviewed_by: reviewedBy,
        reason,
      }).then(r => r.data),
  },

  // ─── Delivery — outbox, jobs, receipts (tenant-scoped) ───────────────────
  delivery: {
    listIntents: (params: Record<string, string | number | undefined> = {}) =>
      restClient.get(`/v1/delivery/intents${buildQS(params as Record<string, string | number | boolean | undefined>)}`, wrap(unknownSchema)).then(r => r.data),
    listJobs: (params: Record<string, string | number | undefined> = {}) =>
      restClient.get(`/v1/delivery/jobs${buildQS(params as Record<string, string | number | boolean | undefined>)}`, wrap(unknownSchema)).then(r => r.data),
    // GET /v1/delivery/jobs/{id} returns { job, attempts } inline — no separate attempts endpoint
    getJob: (jobId: string, tenantId: string) =>
      restClient.get(`/v1/delivery/jobs/${encodeURIComponent(jobId)}?tenantId=${encodeURIComponent(tenantId)}`, wrap(unknownSchema)).then(r => r.data),
    // GET /v1/delivery/receipts — pass intent_id to filter by intent
    listReceipts: (params: Record<string, string | number | undefined> = {}) =>
      restClient.get(`/v1/delivery/receipts${buildQS(params as Record<string, string | number | boolean | undefined>)}`, wrap(unknownSchema)).then(r => r.data),
    // GET /v1/delivery/intents/{id}/receipts — receipts + external links for an intent
    getIntentReceipts: (intentId: string, tenantId: string) =>
      restClient.get(`/v1/delivery/intents/${encodeURIComponent(intentId)}/receipts?tenantId=${encodeURIComponent(tenantId)}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ─── Stablecoin Intelligence (observation-only; raw {items,count} — no envelope) ──
  stablecoins: {
    assets: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/assets${buildQS({ ...params })}`, listSchema),
    deployments: (params?: { canonical_asset_id?: string; chain_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/deployments${buildQS({ ...params })}`, listSchema),
    observations: (params?: { canonical_asset_id?: string; observation_kind?: string; finality_status?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/observations${buildQS({ ...params })}`, listSchema),
    valuations: (params?: { deployment_id?: string; peg_status?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/valuations${buildQS({ ...params })}`, listSchema),
    support: (params?: { canonical_asset_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/support${buildQS({ ...params })}`, listSchema),
    flows: (params?: { canonical_asset_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/flows${buildQS({ ...params })}`, listSchema),
    reconciliation: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/stablecoins/reconciliation${buildQS({ ...params })}`, listSchema),
  },

  // ─── Derivatives Intelligence (observation-only; raw {items,count}) ──────────
  derivatives: {
    venues: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/venues${buildQS({ ...params })}`, listSchema),
    instruments: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/instruments${buildQS({ ...params })}`, listSchema),
    markets: (params?: { venue_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/markets${buildQS({ ...params })}`, listSchema),
    accounts: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/accounts${buildQS({ ...params })}`, listSchema),
    orders: (params?: { trading_account_id?: string; status?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/orders${buildQS({ ...params })}`, listSchema),
    fills: (params?: { trading_account_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/fills${buildQS({ ...params })}`, listSchema),
    positions: (params?: { trading_account_id?: string; status?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/positions${buildQS({ ...params })}`, listSchema),
    pnl: (params?: { trading_account_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/pnl${buildQS({ ...params })}`, listSchema),
    reconciliationVariances: (params?: { severity?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/derivatives/runtime/reconciliation/variances${buildQS({ ...params })}`, listSchema),
  },

  // ─── Interoperability Intelligence (observation-only; raw {items,count}) ─────
  interop: {
    providers: () =>
      restClient.get('/v1/interoperability/providers', listSchema),
    messages: (params?: { status?: string; provider_id?: string; path_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/messages${buildQS({ ...params })}`, listSchema),
    messageDetail: (interopMessageId: string) =>
      restClient.get(`/v1/interoperability/messages/${encodeURIComponent(interopMessageId)}`, z.object({
        message: z.unknown(),
        transitions: z.array(z.unknown()),
        delivery_attempts: z.array(z.unknown()),
        asset_legs: z.array(z.unknown()),
      })),
    paths: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/paths${buildQS({ ...params })}`, listSchema),
    gateways: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/gateways${buildQS({ ...params })}`, listSchema),
    applications: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/applications${buildQS({ ...params })}`, listSchema),
    intents: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/intents${buildQS({ ...params })}`, listSchema),
    assetLegs: (params?: { interop_message_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/asset-legs${buildQS({ ...params })}`, listSchema),
    securityPolicies: (params?: { path_id?: string; limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/security-policies${buildQS({ ...params })}`, listSchema),
    reconciliation: (params?: { limit?: number; offset?: number }) =>
      restClient.get(`/v1/interoperability/reconciliation${buildQS({ ...params })}`, listSchema),
  },
};
