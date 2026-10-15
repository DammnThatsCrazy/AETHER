import { env } from '@aether-app/lib/env';
import { getAccessToken } from '@aether-app/features/auth';

/**
 * Tenant model-selection typed contract (ADR-008 D9).
 *
 * These types are SERVER-shaped: they mirror the model-runtime endpoints and
 * NEVER carry credentials, API keys, or auth material of any kind. Model costs
 * are display-only currency; tenant scope is resolved server-side. The typed
 * fetch client is the ONLY place that attaches transport auth (cookie + access
 * token, mirroring the shared REST client) so the backend can resolve the
 * tenant from `request.state.tenant`.
 */

/** A model entry in the harness model registry as served by the backend. */
export type ModelRegistryModel = {
  modelId: string;
  provider: string;
  status: 'recommended' | 'stable' | 'beta' | 'deprecated' | 'experimental';
  capabilities: string[];
  inputCostPerMTok: number;
  outputCostPerMTok: number;
};

/** Response shape of GET /v1/model-runtime/models. */
export type ModelListResponse = {
  models: ModelRegistryModel[];
  tenantDefaultModel: string | null;
};

/** Reference to a piece of backing evidence for a model capability or claim. */
export type EvidenceRef = {
  referenceId: string;
  source: string;
  snippet?: string;
};

/** Typed tenant-scoped client for the model-runtime endpoints. */
export type TenantModelSelectionApi = {
  getModels(): Promise<ModelListResponse>;
  setTenantDefault(modelId: string): Promise<void>;
};

const MODELS_PATH = '/v1/model-runtime/models';
const TENANT_DEFAULT_PATH = '/v1/model-runtime/tenant-default';

/** Joins the env endpoint (trailing slash tolerant) with an API path. */
function endpointUrl(path: string): string {
  return `${env.VITE_AETHER_ENDPOINT.replace(/\/$/, '')}${path}`;
}

/**
 * Authentication headers mirroring Aether's shared REST client (`restClient`).
 *
 * The model-runtime backend resolves the tenant from `request.state.tenant`,
 * which the auth middleware only populates for authenticated calls. With a
 * cross-origin `VITE_AETHER_ENDPOINT` the browser default of
 * `credentials: "same-origin"` drops the session cookie, so every request here
 * sets `credentials: 'include'` (at the fetch call site) and attaches the OIDC
 * access token the same way `restClient` does. The shared `restClient` itself
 * is not usable for this surface: it resolves against `VITE_API_BASE_URL`
 * rather than the model-runtime endpoint, and its `put` always parses a JSON
 * body while `PUT /v1/model-runtime/tenant-default` responds 204.
 */
function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/**
 * Typed fetch client over the real model-runtime endpoints.
 *
 * Every call sends the same authentication the shared REST client does — the
 * HttpOnly session cookie (`credentials: 'include'`) plus the access token in
 * `Authorization` — so the backend can populate `request.state.tenant` even
 * when `VITE_AETHER_ENDPOINT` is cross-origin.
 *
 * On non-2xx it throws a plain `{ status, message }` object so callers (e.g.
 * the `useModelSelection` hook) can detect an HTTP 403 as the server-
 * authoritative "tenant not entitled to model selection" boundary.
 */
export const defaultModelSelectionApi: TenantModelSelectionApi = {
  async getModels(): Promise<ModelListResponse> {
    const res = await fetch(endpointUrl(MODELS_PATH), {
      method: 'GET',
      headers: authHeaders(),
      credentials: 'include',
    });
    if (!res.ok) {
      throw { status: res.status, message: `Failed to load models (HTTP ${res.status})` };
    }
    return (await res.json()) as ModelListResponse;
  },
  async setTenantDefault(modelId: string): Promise<void> {
    const res = await fetch(endpointUrl(TENANT_DEFAULT_PATH), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      credentials: 'include',
      body: JSON.stringify({ modelId }),
    });
    if (!res.ok) {
      throw {
        status: res.status,
        message: `Failed to set tenant default (HTTP ${res.status})`,
      };
    }
  },
};
