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

// ─── Response wrapper ────────────────────────────────────────────────────────
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const unknownSchema = z.unknown();

const buildQS = (params: Record<string, string | number | boolean | undefined>) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

// ─── API ─────────────────────────────────────────────────────────────────────
export const api = {

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

    /** Cross-session journey chains — steps, drop-off flags, campaign linkage ("where"). */
    journeys: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/journeys`, wrap(unknownSchema)).then(r => r.data as JourneysResponse),

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

    /**
     * Multi-touch attribution — surfaces the "where" of a conversion.
     * Models: multi_touch | first_touch | last_touch | linear | time_decay.
     * Returns weighted credits per channel/source/campaign.
     */
    attribution: (campaignId: string, params?: { model?: string; start_date?: string; end_date?: string }) =>
      restClient.get(`/v1/campaigns/${campaignId}/attribution${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
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

  // ── Notifications (webhooks + alert rules) ────────────────────────────────
  notifications: {
    /** List all webhook configs for this tenant. */
    webhooks: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/notifications/webhooks${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Register a new webhook. */
    createWebhook: (body: Record<string, unknown>) =>
      restClient.post('/v1/notifications/webhooks', wrap(unknownSchema), body).then(r => r.data),

    /** List all alert rules for this tenant. */
    alerts: (tenantId: string, limit = 50) =>
      restClient.get(`/v1/notifications/alerts${buildQS({ tenant_id: tenantId, limit })}`, wrap(unknownSchema)).then(r => r.data),

    /** Create a new alert rule. */
    createAlert: (body: Record<string, unknown>) =>
      restClient.post('/v1/notifications/alerts', wrap(unknownSchema), body).then(r => r.data),
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
  auth: {
    /** Step 1: register email+password → sends 6-digit OTP. */
    register: (body: { name: string; email: string; password: string; plan_tier: string }) =>
      restClient.post('/v1/auth/register', wrap(unknownSchema), body).then(r => r.data),

    /** Step 2: verify OTP code — creates tenant + returns API key. */
    verifyEmail: (email: string, code: string) =>
      restClient.post('/v1/auth/verify-email', wrap(unknownSchema), { email, code })
        .then(r => r.data as { api_key: string; tenant_id: string; name: string }),

    /** Email + password login for returning users. */
    login: (email: string, password: string) =>
      restClient.post('/v1/auth/login', wrap(unknownSchema), { email, password })
        .then(r => r.data as { api_key: string; tenant_id: string }),

    /** Exchange Auth0 JWT for a tenant API key (SSO callback). */
    ssoCallback: (jwt: string) =>
      restClient.post('/v1/auth/sso/callback', wrap(unknownSchema), { jwt })
        .then(r => r.data as { api_key: string }),
  },

  // ── Self-service account (me) ──────────────────────────────────────────────
  me: {
    /** Authenticated tenant profile, plan, and billing. */
    profile: () =>
      restClient.get('/v1/me', wrap(unknownSchema)).then(r => r.data as {
        name: string;
        email: string;
        plan: { plan_id: string; display_name: string; monthly_quota: number; burst_rpm: number };
        billing: { subscription_status: string; current_period_end: string | null };
        api_key_count: number;
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

    /** Permanently delete account and all associated data. */
    deleteAccount: () =>
      restClient.delete('/v1/me/account', wrap(unknownSchema)),
  },

  // ── API key management ─────────────────────────────────────────────────────
  settings: {
    listKeys: () =>
      restClient.get('/v1/me/api-keys', wrap(unknownSchema))
        .then(r => r.data as { keys: Array<{ id: string; name: string; tier: string; permissions: string[]; last_used_at: string | null }> }),

    createKey: (payload: { name: string; tier?: string; permissions?: string[] }) =>
      restClient.post('/v1/me/api-keys', wrap(unknownSchema), payload)
        .then(r => r.data as { id: string; name: string; key: string; api_key: string; tier: string; permissions: string[] }),

    revokeKey: (id: string) =>
      restClient.delete(`/v1/me/api-keys/${id}`, wrap(unknownSchema)),
  },

  // ── Billing & plans ────────────────────────────────────────────────────────
  billing: {
    plans: () =>
      restClient.get('/v1/billing/plans', wrap(unknownSchema))
        .then(r => r.data as { plans: Array<{ plan_id: string; display_name: string; price_monthly: number; monthly_quota: number; burst_rpm: number; features: string[] }> }),

    createCheckout: (priceId: string) =>
      restClient.post('/v1/billing/checkout', wrap(unknownSchema), { price_id: priceId })
        .then(r => r.data as { url: string | null }),

    portal: () =>
      restClient.post('/v1/billing/portal', wrap(unknownSchema))
        .then(r => r.data as { url: string | null }),

    invoices: () =>
      restClient.get('/v1/billing/invoices', wrap(unknownSchema))
        .then(r => r.data as { invoices: Array<{ id: string; amount: number; currency: string; status: string; period_start: string; period_end: string; invoice_url: string | null }> }),

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
    enterprise: (payload: { name: string; email: string; company_name: string; company_type: string; message: string }) =>
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
};

// ─── Utility: call API with typed fallback ────────────────────────────────────
export async function apiCall<T>(
  fetcher: () => Promise<T>,
  fallback: T,
  label: string,
): Promise<{ data: T; fromApi: boolean }> {
  try {
    const data = await fetcher();
    return { data, fromApi: true };
  } catch (err) {
    console.warn(`[API] ${label} failed, using fallback`, err);
    return { data: fallback, fromApi: false };
  }
}
