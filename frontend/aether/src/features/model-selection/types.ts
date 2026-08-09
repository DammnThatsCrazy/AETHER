import { env } from '@aether-app/lib/env';

/**
 * Tenant model-selection typed contract (ADR-008 D9).
 *
 * These types are SERVER-shaped: they mirror the model-runtime endpoints and
 * NEVER carry credentials, API keys, or auth material of any kind. Model costs
 * are display-only currency; tenant scope is resolved server-side.
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
 * Typed fetch client over the real model-runtime endpoints.
 *
 * On non-2xx it throws a plain `{ status, message }` object so callers (e.g.
 * the `useModelSelection` hook) can detect an HTTP 403 as the server-
 * authoritative "tenant not entitled to model selection" boundary.
 */
export const defaultModelSelectionApi: TenantModelSelectionApi = {
  async getModels(): Promise<ModelListResponse> {
    const res = await fetch(endpointUrl(MODELS_PATH));
    if (!res.ok) {
      throw { status: res.status, message: `Failed to load models (HTTP ${res.status})` };
    }
    return (await res.json()) as ModelListResponse;
  },
  async setTenantDefault(modelId: string): Promise<void> {
    const res = await fetch(endpointUrl(TENANT_DEFAULT_PATH), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
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
