/**
 * Typed transport for the canonical `/v1/explore` API.
 *
 * Authentication, correlation ids, CSRF, and runtime base-URL selection remain
 * app-owned concerns. Aether and Kyber provide those through `transport`; this
 * module owns the shared exploration request/response contract, registry
 * validation, and latest-request coordination.
 */

import type {
  ApplicabilityReport,
  ContextLink,
  ExplorationAnchor,
  ExplorationContextV1,
  ExplorationResultEnvelope,
} from '@aether/shared/exploration-contract';
import type {
  FilterExpression,
  FilterGroup,
} from '@aether/shared/graph-contract';
import { isKnownField, isOperatorValidForField } from './registry';

export interface ExplorationApiResponse<T> {
  data: T;
}

export interface ExplorationTransportRequest {
  method: 'GET' | 'POST' | 'DELETE';
  path: string;
  body?: unknown;
  signal?: AbortSignal | undefined;
}

export type ExplorationTransport = <T>(
  request: ExplorationTransportRequest,
) => Promise<ExplorationApiResponse<T>>;

export interface ExplorationRequestOptions {
  signal?: AbortSignal | undefined;
}

export interface ExplorationQueryRequest {
  context: ExplorationContextV1;
  limit?: number | undefined;
  cursor?: string | null | undefined;
}

export interface ExplorationFacetRequest {
  context: ExplorationContextV1;
  fields: string[];
  limit?: number | undefined;
}

export interface FacetBucket {
  value: unknown;
  count: number;
}

export interface ExplorationFacet {
  field: string;
  buckets: FacetBucket[];
  suppressed_bucket_count: number;
  suppressed_record_count: number;
  minimum_cohort_size?: number | null;
  suppression_reason?: string | null;
}

export interface ExplorationFacetData {
  facets: ExplorationFacet[];
  warnings?: string[];
}

export interface SavedExplorationView {
  view_id: string;
  name: string;
  context: ExplorationContextV1;
  created_by: string;
  saved_at: string;
  tenant_id?: string;
}

export interface SaveExplorationViewRequest {
  context: ExplorationContextV1;
  name: string;
  view_id?: string | undefined;
}

export interface ResolveContextLinkRequest {
  context: ExplorationContextV1;
  to: string;
  focus?: ExplorationAnchor | null | undefined;
}

export interface ResolvedContextLink {
  link: ContextLink;
  applicability: ApplicabilityReport;
  adapter_available: boolean;
  warnings: string[];
}

export interface ExplorationValidationResult {
  normalized_context: ExplorationContextV1;
  surface: string;
  surface_registered: boolean;
  adapter_available: boolean;
  applicability: ApplicabilityReport;
  routed_filter_count: number;
  warnings: string[];
}

export class ExplorationClientValidationError extends Error {
  constructor(public readonly issues: readonly string[]) {
    super(`Invalid exploration request: ${issues.join(', ')}`);
    this.name = 'ExplorationClientValidationError';
  }
}

/** Raised when a newer request has replaced this response for the same key. */
export class StaleExplorationResponseError extends Error {
  constructor(public readonly key: string) {
    super(`Exploration response was superseded for "${key}"`);
    this.name = 'StaleExplorationResponseError';
  }
}

function isGroup(node: FilterExpression | FilterGroup): node is FilterGroup {
  return 'logic' in node;
}

function filterIssues(group: FilterGroup, path = 'population'): string[] {
  const issues: string[] = [];
  group.expressions.forEach((node, index) => {
    const nodePath = `${path}.expressions[${index}]`;
    if (isGroup(node)) {
      issues.push(...filterIssues(node, nodePath));
      return;
    }
    if (!isKnownField(node.field)) {
      issues.push(`${nodePath}.field:${node.field}:not_registered`);
    } else if (!isOperatorValidForField(node.field, node.op)) {
      issues.push(`${nodePath}.op:${node.op}:not_registered_for:${node.field}`);
    }
  });
  return issues;
}

/**
 * Fail closed before a query leaves the browser. Unlike the URL sanitizer,
 * request validation never drops a filter: callers must correct every invalid
 * nested leaf, preserving the fabric's no-silent-drop invariant.
 */
export function assertRegistryValidContext(context: ExplorationContextV1): void {
  const issues = context.population ? filterIssues(context.population) : [];
  if (issues.length) throw new ExplorationClientValidationError(issues);
}

function assertFacetFields(fields: readonly string[]): void {
  const issues = fields
    .filter((field) => !isKnownField(field))
    .map((field) => `facets.field:${field}:not_registered`);
  if (issues.length) throw new ExplorationClientValidationError(issues);
}

function withOptional<T extends object, K extends string, V>(
  value: T,
  key: K,
  optional: V | null | undefined,
): T & Partial<Record<K, V>> {
  return optional === null || optional === undefined
    ? value
    : { ...value, [key]: optional };
}

export interface ExplorationClient {
  validate(
    context: ExplorationContextV1,
    options?: ExplorationRequestOptions,
  ): Promise<ExplorationValidationResult>;
  query<T = unknown>(
    request: ExplorationQueryRequest,
    options?: ExplorationRequestOptions,
  ): Promise<ExplorationResultEnvelope<T>>;
  queryLatest<T = unknown>(
    request: ExplorationQueryRequest,
    options?: ExplorationRequestOptions & { key?: string | undefined },
  ): Promise<ExplorationResultEnvelope<T>>;
  facets(
    request: ExplorationFacetRequest,
    options?: ExplorationRequestOptions,
  ): Promise<ExplorationResultEnvelope<ExplorationFacetData>>;
  facetsLatest(
    request: ExplorationFacetRequest,
    options?: ExplorationRequestOptions & { key?: string | undefined },
  ): Promise<ExplorationResultEnvelope<ExplorationFacetData>>;
  listViews(
    pagination?: { limit?: number | undefined; offset?: number | undefined },
    options?: ExplorationRequestOptions,
  ): Promise<SavedExplorationView[]>;
  saveView(
    request: SaveExplorationViewRequest,
    options?: ExplorationRequestOptions,
  ): Promise<SavedExplorationView>;
  getView(
    viewId: string,
    options?: ExplorationRequestOptions,
  ): Promise<SavedExplorationView>;
  deleteView(viewId: string, options?: ExplorationRequestOptions): Promise<string>;
  resolveLink(
    request: ResolveContextLinkRequest,
    options?: ExplorationRequestOptions,
  ): Promise<ResolvedContextLink>;
  cancelLatest(key?: string): void;
}

export function createExplorationClient(transport: ExplorationTransport): ExplorationClient {
  const generations = new Map<string, number>();
  const controllers = new Map<string, AbortController>();

  const post = async <T>(
    path: string,
    body: unknown,
    signal?: AbortSignal,
  ): Promise<T> => (await transport<T>({ method: 'POST', path, body, signal })).data;

  const latest = async <T>(
    key: string,
    externalSignal: AbortSignal | undefined,
    execute: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> => {
    controllers.get(key)?.abort();
    const generation = (generations.get(key) ?? 0) + 1;
    generations.set(key, generation);

    const controller = new AbortController();
    controllers.set(key, controller);
    const abortFromCaller = () => controller.abort();
    externalSignal?.addEventListener('abort', abortFromCaller, { once: true });
    if (externalSignal?.aborted) controller.abort();

    try {
      const result = await execute(controller.signal);
      if (generations.get(key) !== generation) {
        throw new StaleExplorationResponseError(key);
      }
      return result;
    } catch (error) {
      if (generations.get(key) !== generation) {
        throw new StaleExplorationResponseError(key);
      }
      throw error;
    } finally {
      externalSignal?.removeEventListener('abort', abortFromCaller);
      if (generations.get(key) === generation) controllers.delete(key);
    }
  };

  const query = async <T>(
    request: ExplorationQueryRequest,
    options?: ExplorationRequestOptions,
  ): Promise<ExplorationResultEnvelope<T>> => {
    assertRegistryValidContext(request.context);
    let body = withOptional({ context: request.context }, 'limit', request.limit);
    body = withOptional(body, 'cursor', request.cursor);
    const data = await post<{ envelope: ExplorationResultEnvelope<T> }>(
      '/v1/explore/query',
      body,
      options?.signal,
    );
    return data.envelope;
  };

  const facets = async (
    request: ExplorationFacetRequest,
    options?: ExplorationRequestOptions,
  ): Promise<ExplorationResultEnvelope<ExplorationFacetData>> => {
    assertRegistryValidContext(request.context);
    assertFacetFields(request.fields);
    const body = withOptional(
      { context: request.context, fields: request.fields },
      'limit',
      request.limit,
    );
    const data = await post<{
      envelope: ExplorationResultEnvelope<ExplorationFacetData>;
    }>('/v1/explore/facets', body, options?.signal);
    return data.envelope;
  };

  return {
    async validate(context, options) {
      assertRegistryValidContext(context);
      return post<ExplorationValidationResult>(
        '/v1/explore/validate',
        { context },
        options?.signal,
      );
    },
    query,
    queryLatest(request, options) {
      return latest(
        options?.key ?? `query:${request.context.scope.surface}`,
        options?.signal,
        (signal) => query(request, { signal }),
      );
    },
    facets,
    facetsLatest(request, options) {
      return latest(
        options?.key ?? `facets:${request.context.scope.surface}`,
        options?.signal,
        (signal) => facets(request, { signal }),
      );
    },
    async listViews(pagination, options) {
      const queryParams = new URLSearchParams();
      if (pagination?.limit !== undefined) queryParams.set('limit', String(pagination.limit));
      if (pagination?.offset !== undefined) queryParams.set('offset', String(pagination.offset));
      const suffix = queryParams.size ? `?${queryParams.toString()}` : '';
      const response = await transport<{ views: SavedExplorationView[] }>({
        method: 'GET',
        path: `/v1/explore/views${suffix}`,
        signal: options?.signal,
      });
      return response.data.views;
    },
    async saveView(request, options) {
      assertRegistryValidContext(request.context);
      const body = withOptional(
        { context: request.context, name: request.name },
        'view_id',
        request.view_id,
      );
      const data = await post<{ view: SavedExplorationView }>(
        '/v1/explore/views',
        body,
        options?.signal,
      );
      return data.view;
    },
    async getView(viewId, options) {
      const response = await transport<{ view: SavedExplorationView }>({
        method: 'GET',
        path: `/v1/explore/views/${encodeURIComponent(viewId)}`,
        signal: options?.signal,
      });
      return response.data.view;
    },
    async deleteView(viewId, options) {
      const response = await transport<{ deleted: string }>({
        method: 'DELETE',
        path: `/v1/explore/views/${encodeURIComponent(viewId)}`,
        signal: options?.signal,
      });
      return response.data.deleted;
    },
    resolveLink(request, options) {
      assertRegistryValidContext(request.context);
      const body = withOptional(
        { context: request.context, to: request.to },
        'focus',
        request.focus,
      );
      return post<ResolvedContextLink>('/v1/explore/links/resolve', body, options?.signal);
    },
    cancelLatest(key) {
      if (key !== undefined) {
        controllers.get(key)?.abort();
        controllers.delete(key);
        generations.set(key, (generations.get(key) ?? 0) + 1);
        return;
      }
      for (const [activeKey, controller] of controllers) {
        controller.abort();
        generations.set(activeKey, (generations.get(activeKey) ?? 0) + 1);
      }
      controllers.clear();
    },
  };
}
