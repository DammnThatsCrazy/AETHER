/**
 * Typed contract for the Kyber model-runtime admin surfaces.
 *
 * These types are server-shaped (ADR-008 D8/D9): every field mirrors what the
 * model-runtime control plane returns over `/v1/model-runtime/*`. They never
 * carry credentials or provider API keys — capabilities/costs/status only.
 *
 * All five model-runtime pages (ModelRegistryPage, ModelRuntimeHealthPage,
 * EntitlementsPage, UsagePage, TracesPage) build against these EXACT names.
 */

export type RegistryModel = {
  modelId: string;
  provider: string;
  status: 'recommended' | 'stable' | 'beta' | 'deprecated' | 'experimental';
  capabilities: string[];
  inputCostPerMTok: number;
  outputCostPerMTok: number;
};

export type RegistryResponse = {
  models: RegistryModel[];
};

export type ProviderHealth = {
  provider: string;
  configured: boolean;
  healthy: boolean;
  reason: string;
};

export type HealthResponse = {
  status: 'ok' | 'degraded' | 'unhealthy';
  providers: ProviderHealth[];
  checks: Record<string, boolean>;
};

export type EntitlementRow = {
  tenantId: string;
  modelId: string;
  entitled: boolean;
  reason?: string | null;
};

export type EntitlementsResponse = {
  entitlements: EntitlementRow[];
};

export type UsageTotals = {
  calls: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
};

export type UsageByModel = {
  modelId: string;
} & UsageTotals;

export type UsageResponse = {
  period: string;
  totals: UsageTotals;
  byModel: UsageByModel[];
};

export type RoutingTrace = {
  traceId: string;
  correlationId: string | null;
  tenantId: string;
  profileId: string;
  requestedModel: string | null;
  selectedModel: string;
  mode: string;
  entitled: boolean;
  fallback: boolean;
  status: string;
  latencyMs: number;
  createdAt: string;
};

export type TracesResponse = {
  traces: RoutingTrace[];
};

export type ModelRuntimeAdminApi = {
  fetchRegistry(): Promise<RegistryResponse>;
  fetchHealth(): Promise<HealthResponse>;
  fetchEntitlements(): Promise<EntitlementsResponse>;
  fetchUsage(): Promise<UsageResponse>;
  fetchTraces(): Promise<TracesResponse>;
};

/**
 * Resolve the model-runtime admin base URL.
 *
 * `VITE_KYBER_ENDPOINT` is the dedicated knob for the model-runtime control
 * plane; when unset (e.g. in the vitest env) we fall back to the existing Kyber
 * backend env var `VITE_API_BASE_URL` so the typed clients remain runnable
 * against the same operator backend. Wiring to real endpoints is a later
 * integration step — clients only fail cleanly today.
 */
function resolveModelRuntimeBase(): string {
  const dedicated = (import.meta.env.VITE_KYBER_ENDPOINT ?? '').trim().replace(/\/$/, '');
  if (dedicated) return dedicated;
  const fallback = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/$/, '');
  return fallback || 'http://localhost:8000';
}

async function modelRuntimeRequest<T>(
  resource: string,
): Promise<T> {
  const base = resolveModelRuntimeBase();
  const response = await fetch(`${base}/v1/model-runtime/${resource}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    // Fail cleanly with a status-shaped error; no credential material.
    throw { status: response.status, message: response.statusText || `model-runtime ${resource} failed` };
  }
  return (await response.json()) as T;
}

/**
 * Default typed fetch client for the model-runtime admin surfaces.
 * The sibling page modules consume this until real backend wiring lands.
 */
export const defaultModelRuntimeAdminApi: ModelRuntimeAdminApi = {
  fetchRegistry: () => modelRuntimeRequest<RegistryResponse>('registry'),
  fetchHealth: () => modelRuntimeRequest<HealthResponse>('health'),
  fetchEntitlements: () => modelRuntimeRequest<EntitlementsResponse>('entitlements'),
  fetchUsage: () => modelRuntimeRequest<UsageResponse>('usage'),
  fetchTraces: () => modelRuntimeRequest<TracesResponse>('traces'),
};
