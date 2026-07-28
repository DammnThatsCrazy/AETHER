import { describe, expect, it, vi } from 'vitest';
import type {
  ExplorationContextV1,
  ExplorationResultEnvelope,
} from '@aether/shared/exploration-contract';
import type {
  ExplorationApiResponse,
  ExplorationTransport,
  ExplorationTransportRequest,
} from './client';
import {
  createExplorationClient,
  ExplorationClientValidationError,
  StaleExplorationResponseError,
} from './client';

function context(): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: 'tenant-1', surface: 'graph' },
    population: {
      logic: 'AND',
      expressions: [
        { field: 'entity.type', op: 'eq', value: 'person' },
        {
          logic: 'OR',
          expressions: [
            { field: 'risk.score', op: 'gte', value: 0.8 },
            { field: 'geography.country', op: 'in', value: ['US', 'CA'] },
          ],
        },
      ],
    },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  };
}

function envelope(queryId: string): ExplorationResultEnvelope<{ nodes: [] }> {
  return {
    contract_version: '1',
    query_id: queryId,
    normalized_context: context(),
    data: { nodes: [] },
    completeness: { complete: true, sampled: false, truncated: false },
    truth: { overall_state: 'ready', dimensions: [] },
    applicability: { entries: [] },
    execution: { duration_ms: 1, cache_status: 'miss', adapters: ['graph'] },
    warnings: [],
  };
}

describe('exploration client', () => {
  it('preserves the complete nested filter tree in a typed query request', async () => {
    const transportMock = vi.fn(async (request: ExplorationTransportRequest) => ({
      data: { envelope: envelope('q1') },
    }));
    const transport: ExplorationTransport = <T>(request: ExplorationTransportRequest) =>
      transportMock(request) as unknown as Promise<ExplorationApiResponse<T>>;
    const client = createExplorationClient(transport);

    await client.query({ context: context(), limit: 75, cursor: 'next' });

    expect(transportMock).toHaveBeenCalledWith({
      method: 'POST',
      path: '/v1/explore/query',
      body: { context: context(), limit: 75, cursor: 'next' },
      signal: undefined,
    });
  });

  it('fails closed on an invalid leaf anywhere in a nested group', async () => {
    const invalid = context();
    invalid.population = {
      logic: 'AND',
      expressions: [
        {
          logic: 'OR',
          expressions: [{ field: 'user.email', op: 'eq', value: 'private@example.com' }],
        },
      ],
    };
    const transportMock = vi.fn();
    const transport: ExplorationTransport = <T>(request: ExplorationTransportRequest) =>
      transportMock(request) as unknown as Promise<ExplorationApiResponse<T>>;
    const client = createExplorationClient(transport);

    await expect(client.query({ context: invalid })).rejects.toMatchObject({
      name: 'ExplorationClientValidationError',
      issues: ['population.expressions[0].expressions[0].field:user.email:not_registered'],
    } satisfies Partial<ExplorationClientValidationError>);
    expect(transportMock).not.toHaveBeenCalled();
  });

  it('rejects unregistered facet fields before transport', async () => {
    const transportMock = vi.fn();
    const transport: ExplorationTransport = <T>(request: ExplorationTransportRequest) =>
      transportMock(request) as unknown as Promise<ExplorationApiResponse<T>>;
    const client = createExplorationClient(transport);
    await expect(
      client.facets({ context: context(), fields: ['geography.country', 'user.email'] }),
    ).rejects.toBeInstanceOf(ExplorationClientValidationError);
    expect(transportMock).not.toHaveBeenCalled();
  });

  it('covers facets, saved views, and context-link endpoint shapes', async () => {
    const requests: ExplorationTransportRequest[] = [];
    const transport: ExplorationTransport = async <T>(request: ExplorationTransportRequest) => {
      requests.push(request);
      let data: unknown;
      if (request.path === '/v1/explore/facets') {
        data = { envelope: { ...envelope('f1'), data: { facets: [] } } };
      } else if (request.path.startsWith('/v1/explore/views?')) {
        data = { views: [] };
      } else if (request.path === '/v1/explore/views' && request.method === 'POST') {
        data = {
          view: {
            view_id: 'view-1',
            name: 'Risk',
            context: context(),
            created_by: 'u1',
            saved_at: '2026-07-28T00:00:00Z',
          },
        };
      } else {
        data = {
          link: {
            to: 'geo',
            context: { ...context(), scope: { ...context().scope, surface: 'geo' } },
          },
          applicability: { entries: [] },
          adapter_available: true,
          warnings: [],
        };
      }
      return { data: data as T };
    };
    const client = createExplorationClient(transport);

    await client.facets({ context: context(), fields: ['geography.country'] });
    await client.listViews({ limit: 20, offset: 5 });
    await client.saveView({ context: context(), name: 'Risk' });
    await client.resolveLink({ context: context(), to: 'geo' });

    expect(requests.map(({ method, path }) => `${method} ${path}`)).toEqual([
      'POST /v1/explore/facets',
      'GET /v1/explore/views?limit=20&offset=5',
      'POST /v1/explore/views',
      'POST /v1/explore/links/resolve',
    ]);
  });

  it('aborts the prior keyed request and rejects a late response as stale', async () => {
    const resolvers: Array<
      (value: { data: { envelope: ExplorationResultEnvelope<{ nodes: [] }> } }) => void
    > = [];
    const signals: AbortSignal[] = [];
    const transport: ExplorationTransport = <T>(request: ExplorationTransportRequest) =>
      new Promise<ExplorationApiResponse<T>>((resolve) => {
        signals.push(request.signal!);
        resolvers.push((value) => resolve(value as unknown as ExplorationApiResponse<T>));
      });
    const client = createExplorationClient(transport);

    const first = client.queryLatest<{ nodes: [] }>({ context: context() }, { key: 'workspace' });
    const second = client.queryLatest<{ nodes: [] }>({ context: context() }, { key: 'workspace' });
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);

    resolvers[0]?.({ data: { envelope: envelope('old') } });
    resolvers[1]?.({ data: { envelope: envelope('new') } });

    await expect(first).rejects.toBeInstanceOf(StaleExplorationResponseError);
    await expect(second).resolves.toMatchObject({ query_id: 'new' });
  });
});
