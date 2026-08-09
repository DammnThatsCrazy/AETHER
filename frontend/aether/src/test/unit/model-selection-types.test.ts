import { afterEach, describe, expect, it, vi } from 'vitest';
import { expectTypeOf } from 'vitest';
import * as modelSelection from '@aether-app/features/model-selection';
import { defaultModelSelectionApi } from '@aether-app/features/model-selection/types';
import type {
  EvidenceRef,
  ModelListResponse,
  ModelRegistryModel,
  TenantModelSelectionApi,
} from '@aether-app/features/model-selection/types';

// C13-F owns the model-selection typed contract + public barrel. These are
// type-level + runtime checks that the contract is server-shaped, never leaks
// credentials, and that the typed fetch client fails cleanly on non-2xx.

afterEach(() => {
  vi.unstubAllGlobals();
});

const MODELS: ModelRegistryModel[] = [
  {
    modelId: 'anthropic/claude-sonnet-4',
    provider: 'anthropic',
    status: 'recommended',
    capabilities: ['text'],
    inputCostPerMTok: 3,
    outputCostPerMTok: 15,
  },
];

describe('model-selection typed contract (types.ts)', () => {
  it('shapes the server model registry entry without credential fields', () => {
    expectTypeOf<ModelRegistryModel>().toMatchTypeOf<{
      modelId: string;
      provider: string;
      status: 'recommended' | 'stable' | 'beta' | 'deprecated' | 'experimental';
      capabilities: string[];
      inputCostPerMTok: number;
      outputCostPerMTok: number;
    }>();
    expectTypeOf<ModelRegistryModel>().not.toHaveProperty('apiKey');
    expectTypeOf<ModelRegistryModel>().not.toHaveProperty('credentials');
    expectTypeOf<ModelRegistryModel>().not.toHaveProperty('secret');
  }, 15_000);

  it('shapes the list response and evidence reference', () => {
    expectTypeOf<ModelListResponse>().toMatchTypeOf<{
      models: ModelRegistryModel[];
      tenantDefaultModel: string | null;
    }>();
    expectTypeOf<ModelListResponse>().not.toHaveProperty('authorization');
    expectTypeOf<EvidenceRef>().toHaveProperty('referenceId').toEqualTypeOf<string>();
    expectTypeOf<EvidenceRef>().toHaveProperty('source').toEqualTypeOf<string>();
    expectTypeOf<EvidenceRef>().toHaveProperty('snippet').toEqualTypeOf<string | undefined>();
  }, 15_000);

  it('types the tenant api client surface', () => {
    expectTypeOf<TenantModelSelectionApi>()
      .toHaveProperty('getModels')
      .returns.toEqualTypeOf<Promise<ModelListResponse>>();
    expectTypeOf<TenantModelSelectionApi>()
      .toHaveProperty('setTenantDefault')
      .parameter(0)
      .toEqualTypeOf<string>();
    expectTypeOf(defaultModelSelectionApi).toMatchTypeOf<TenantModelSelectionApi>();
    expectTypeOf<TenantModelSelectionApi>().not.toHaveProperty('apiKey');
  }, 15_000);
});

describe('defaultModelSelectionApi (typed fetch client)', () => {
  it('exposes exactly the getModels + setTenantDefault methods', () => {
    expect(typeof defaultModelSelectionApi).toBe('object');
    expect(Object.keys(defaultModelSelectionApi).sort()).toEqual(['getModels', 'setTenantDefault']);
    expect(typeof defaultModelSelectionApi.getModels).toBe('function');
    expect(typeof defaultModelSelectionApi.setTenantDefault).toBe('function');
  }, 15_000);

  it('parses a resolved fetch Response into ModelListResponse data', async () => {
    const payload: ModelListResponse = {
      models: MODELS,
      tenantDefaultModel: 'anthropic/claude-sonnet-4',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const result = await defaultModelSelectionApi.getModels();

    expect(result).toEqual(payload);
    expect(result.models[0]?.modelId).toBe('anthropic/claude-sonnet-4');
    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/v1/model-runtime/models');
  }, 15_000);

  it('rejects with { status: 403 } when the endpoint denies the tenant', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'not entitled' }), { status: 403 })),
    );

    await expect(defaultModelSelectionApi.getModels()).rejects.toMatchObject({ status: 403 });
    await expect(defaultModelSelectionApi.setTenantDefault('openai/gpt-4o')).rejects.toMatchObject({ status: 403 });
  }, 15_000);
});

describe('model-selection public barrel (index.ts)', () => {
  it('exports the 5 public names + the typed client', () => {
    expect(modelSelection.ModelSelectionPanel).toBeTypeOf('function');
    expect(modelSelection.ModelRegistryView).toBeTypeOf('function');
    expect(modelSelection.EntitlementBadge).toBeTypeOf('function');
    expect(modelSelection.EvidenceReferences).toBeTypeOf('function');
    expect(modelSelection.useModelSelection).toBeTypeOf('function');
    expect(modelSelection.defaultModelSelectionApi).toBeTypeOf('object');
    expect(modelSelection.defaultModelSelectionApi.getModels).toBeTypeOf('function');
    expect(modelSelection.defaultModelSelectionApi.setTenantDefault).toBeTypeOf('function');
  }, 15_000);
});
