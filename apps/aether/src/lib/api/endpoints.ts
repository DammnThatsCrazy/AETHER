/**
 * AETHER customer API endpoints.
 * Covers: Profile & Identity, Consent & Privacy, Rewards & Campaigns, Web3 & On-Chain.
 * All REST responses are wrapped in { data, status, timestamp }.
 */
import { z } from 'zod';
import { restClient } from './rest/client';

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

// ─── Shared schemas ───────────────────────────────────────────────────────────
const profileSchema = z.object({
  user_id: z.string().optional(),
  events: z.array(z.unknown()).optional(),
  connections: z.array(z.unknown()).optional(),
  timeline: z.array(z.unknown()).optional(),
  identifiers: z.array(z.unknown()).optional(),
}).passthrough();

// ─── Customer API ─────────────────────────────────────────────────────────────
export const api = {

  // ── Profile & Identity ─────────────────────────────────────────────────────
  profile: {
    me: () =>
      restClient.get('/v1/profile/me', wrap(profileSchema)).then(r => r.data),

    full: (userId: string) =>
      restClient.get(`/v1/profile/${userId}?include_timeline=true&include_graph=true`, wrap(profileSchema)).then(r => r.data),

    timeline: (userId: string, limit = 50) =>
      restClient.get(`/v1/profile/${userId}/timeline?limit=${limit}`, wrap(z.object({
        user_id: z.string(), events: z.array(z.unknown()), count: z.number(),
      }))).then(r => r.data),

    graph: (userId: string) =>
      restClient.get(`/v1/profile/${userId}/graph`, wrap(unknownSchema)).then(r => r.data),

    resolve: (params: { wallet?: string; email?: string; device?: string }) =>
      restClient.get(`/v1/profile/resolve${buildQS(params)}`, wrap(z.object({ resolved_user_id: z.string() }))).then(r => r.data),
  },

  // ── Profile360 normalized view ─────────────────────────────────────────────
  profile360: {
    full: (entityType: string, entityId: string) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}?include=identity,financial,graph,timeline`, wrap(unknownSchema)).then(r => r.data),

    graph: (entityType: string, entityId: string, params?: { cursor?: string; limit?: number }) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}/graph${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),

    timeline: (entityType: string, entityId: string, params?: { cursor?: string; limit?: number; type?: string }) =>
      restClient.get(`/v1/profile360/${entityType}/${entityId}/timeline${buildQS({ ...params })}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Identity ───────────────────────────────────────────────────────────────
  identity: {
    getProfile: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}`, wrap(profileSchema)).then(r => r.data),

    graphNeighborhood: (userId: string) =>
      restClient.get(`/v1/identity/profiles/${userId}/graph`, wrap(z.object({ user_id: z.string(), connections: z.array(z.unknown()) }).passthrough())).then(r => r.data),
  },

  // ── Resolution (read-only — identity cluster lookup) ──────────────────────
  resolution: {
    cluster: (userId: string) =>
      restClient.get(`/v1/resolution/cluster/${userId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Consent & Privacy ──────────────────────────────────────────────────────
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
  },

  // ── Rewards ────────────────────────────────────────────────────────────────
  rewards: {
    evaluate: (event: { event_type: string; user_address: string; channel?: string; session_id?: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/rewards/evaluate', wrap(unknownSchema), event).then(r => r.data),

    listCampaigns: (params?: { status?: string; limit?: number }) =>
      restClient.get(`/v1/rewards/campaigns${buildQS({ ...params })}`, wrap(z.object({ campaigns: z.array(z.unknown()), count: z.number() }))).then(r => r.data),

    getCampaign: (campaignId: string) =>
      restClient.get(`/v1/rewards/campaigns/${campaignId}`, wrap(unknownSchema)).then(r => r.data),

    userRewards: (address: string) =>
      restClient.get(`/v1/rewards/user/${address}`, wrap(unknownSchema)).then(r => r.data),

    getProof: (rewardId: string) =>
      restClient.get(`/v1/rewards/proof/${rewardId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Attribution (touchpoint recording for campaigns) ───────────────────────
  attribution: {
    recordTouchpoint: (touchpoint: { user_id: string; channel: string; source: string; campaign?: string; event_type: string; timestamp: string; properties?: Record<string, unknown> }) =>
      restClient.post('/v1/attribution/touchpoints', wrap(unknownSchema), touchpoint).then(r => r.data),

    journey: (userId: string) =>
      restClient.get(`/v1/attribution/journey/${userId}`, wrap(unknownSchema)).then(r => r.data),
  },

  // ── Web3 (read-oriented customer subset) ──────────────────────────────────
  web3: {
    chains: {
      list: (params?: { vm_family?: string; limit?: number }) =>
        restClient.get(`/v1/web3/chains${buildQS({ ...params })}`, wrap(z.array(unknownSchema))).then(r => r.data),
      get: (chainId: string) =>
        restClient.get(`/v1/web3/chains/${chainId}`, wrap(unknownSchema)).then(r => r.data),
    },
    protocols: {
      list: (params?: { family?: string; chain?: string; q?: string; limit?: number }) =>
        restClient.get(`/v1/web3/protocols${buildQS({ ...params })}`, wrap(z.array(unknownSchema))).then(r => r.data),
      get: (protocolId: string) =>
        restClient.get(`/v1/web3/protocols/${protocolId}`, wrap(unknownSchema)).then(r => r.data),
    },
    tokens: {
      list: (params?: { chain_id?: string; stablecoins?: boolean; limit?: number }) =>
        restClient.get(`/v1/web3/tokens${buildQS({ ...params })}`, wrap(z.array(unknownSchema))).then(r => r.data),
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
        restClient.get(`/v1/web3/governance/spaces${buildQS({ ...params })}`, wrap(z.array(unknownSchema))).then(r => r.data),
    },
    classify: {
      observation: (observation: Record<string, unknown>) =>
        restClient.post('/v1/web3/classify/observation', wrap(unknownSchema), observation).then(r => r.data),
    },
  },

  // ── On-Chain ───────────────────────────────────────────────────────────────
  onchain: {
    agentActions: (agentId: string) =>
      restClient.get(`/v1/onchain/actions/${agentId}`, wrap(z.array(unknownSchema))).then(r => r.data),

    getContract: (address: string) =>
      restClient.get(`/v1/onchain/contracts/${address}`, wrap(unknownSchema)).then(r => r.data),

    rpcHealth: () =>
      restClient.get('/v1/onchain/rpc/health', wrap(unknownSchema)).then(r => r.data),
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
        restClient.get(`/v1/flows/wallets${buildQS({ entity_id: entityId, limit })}`, wrap(z.array(unknownSchema))).then(r => r.data),
      link: (wallet: { owner_entity_id: string; chain: string; address: string }) =>
        restClient.post('/v1/flows/wallets', wrap(unknownSchema), wallet).then(r => r.data),
    },
    transfers: {
      list: (entityId: string, limit = 50) =>
        restClient.get(`/v1/flows/transfers${buildQS({ entity_id: entityId, limit })}`, wrap(z.array(unknownSchema))).then(r => r.data),
    },
    assets: {
      get: (assetId: string) =>
        restClient.get(`/v1/flows/assets/${assetId}`, wrap(unknownSchema)).then(r => r.data),
    },
  },

  // ── Providers (health + categories — customer-safe subset) ────────────────
  providers: {
    health: () =>
      restClient.get('/v1/providers/health', wrap(unknownSchema)).then(r => r.data),

    categories: () =>
      restClient.get('/v1/providers/categories', wrap(z.array(unknownSchema))).then(r => r.data),
  },

  // ── Ingestion (SDK event capture) ─────────────────────────────────────────
  ingest: {
    event: (event: { event_type: string; session_id: string; properties?: Record<string, unknown>; timestamp?: string; user_id?: string; device_id?: string }) =>
      restClient.post('/v1/ingest/events', wrap(unknownSchema), event).then(r => r.data),

    batch: (events: unknown[]) =>
      restClient.post('/v1/ingest/events/batch', wrap(unknownSchema), { events }).then(r => r.data),
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
