import { randomUUID } from 'node:crypto';

const DEFAULT_API_URL = 'https://api.aether.io';
const REQUEST_TIMEOUT_MS = 15_000;
const CAPABILITY_ID_PATTERN = /^cap_[a-f0-9]{24}$/;
const SITE_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_INGEST_BODY_BYTES = 64 * 1024;
export const MAX_ENTITY_PAGE_SIZE = 50;

export class AccessApiError extends Error {
  constructor(message, { status, code, requestId, apiRequestId } = {}) {
    super(message);
    this.name = 'AccessApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.apiRequestId = apiRequestId;
  }
}

function isLoopback(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  return normalized === 'localhost'
    || normalized === '127.0.0.1'
    || normalized === '::1';
}

function readApiOrigin(env = process.env) {
  const rawUrl = env.AETHER_API_URL || DEFAULT_API_URL;
  let apiUrl;
  try {
    apiUrl = new URL(rawUrl);
  } catch {
    throw new Error('AETHER_API_URL must be a valid HTTP or HTTPS origin.');
  }

  if (!['https:', 'http:'].includes(apiUrl.protocol)
      || apiUrl.username
      || apiUrl.password
      || apiUrl.search
      || apiUrl.hash
      || !['', '/'].includes(apiUrl.pathname)) {
    throw new Error('AETHER_API_URL must be an origin URL without credentials, path, query, or fragment.');
  }
  if (apiUrl.protocol !== 'https:' && !isLoopback(apiUrl.hostname)) {
    throw new Error('AETHER_API_URL must use HTTPS except for localhost development.');
  }

  return apiUrl.origin;
}

export function readConfig(env = process.env) {
  const apiOrigin = readApiOrigin(env);

  const apiKey = env.AETHER_API_KEY;
  if (!apiKey || !apiKey.trim()) {
    throw new Error('Set AETHER_API_KEY to a tenant-scoped Aether API key.');
  }

  return { apiOrigin, apiKey };
}

export function readPublishableConfig(env = process.env) {
  const apiOrigin = readApiOrigin(env);
  const publishableKey = env.AETHER_PUBLISHABLE_KEY;
  const siteId = env.AETHER_SITE_ID;
  if (!publishableKey || !publishableKey.trim()) {
    throw new Error('Set AETHER_PUBLISHABLE_KEY to a site-bound publishable key.');
  }
  if (!publishableKey.startsWith('pk_')) {
    throw new Error('AETHER_PUBLISHABLE_KEY must use the pk_ publishable-key prefix.');
  }
  if (!siteId || !SITE_ID_PATTERN.test(siteId)) {
    throw new Error('Set AETHER_SITE_ID to the bounded site ID bound to AETHER_PUBLISHABLE_KEY.');
  }
  return { apiOrigin, publishableKey, siteId };
}

async function readRequest(path, query = undefined, env = process.env) {
  const { apiOrigin, apiKey } = readConfig(env);
  const url = new URL(path, `${apiOrigin}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
    }
  }

  const correlationId = randomUUID();
  let response;
  try {
    response = await fetch(url, {
      method: 'GET',
      redirect: 'error',
      headers: {
        accept: 'application/json',
        authorization: `Bearer ${apiKey}`,
        'x-correlation-id': correlationId,
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const reason = error?.name === 'TimeoutError' ? 'request timed out' : 'could not reach the Aether API';
    throw new AccessApiError(reason, { requestId: correlationId });
  }

  const headerCorrelationId = response.headers.get('x-correlation-id');
  const headerRequestId = headerCorrelationId || response.headers.get('x-request-id') || correlationId;
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new AccessApiError(`Aether API returned a non-JSON response (HTTP ${response.status}).`, {
      status: response.status,
      requestId: headerRequestId,
    });
  }

  if (!response.ok) {
    const errorCode = payload?.error?.code ?? payload?.code;
    const apiRequestId = typeof payload?.meta?.request_id === 'string'
      ? payload.meta.request_id
      : (typeof payload?.request_id === 'string' ? payload.request_id : undefined);
    throw new AccessApiError(
      `Aether API request failed (HTTP ${response.status}${errorCode ? `, ${errorCode}` : ''}).`,
      { status: response.status, code: errorCode, requestId: headerRequestId, apiRequestId },
    );
  }

  if (!payload || typeof payload !== 'object' || !Object.hasOwn(payload, 'data')) {
    throw new AccessApiError('Aether API returned an unexpected response envelope.', {
      status: response.status,
      requestId: headerRequestId,
    });
  }

  return {
    data: payload.data,
    requestId: headerRequestId,
    responseRequestId: typeof payload.meta?.request_id === 'string'
      ? payload.meta.request_id
      : (typeof payload.request_id === 'string' ? payload.request_id : undefined),
  };
}

function safeCapability(row) {
  if (!row || typeof row !== 'object') return null;
  return {
    capability_id: row.capability_id,
    capability_kind: row.capability_kind ?? 'unknown',
    provider: row.provider ?? null,
    server_name: row.server_name ?? null,
    tool_name: row.tool_name ?? null,
    protocol_version: row.protocol_version ?? null,
    latest_risk_level: row.latest_risk_level ?? null,
    discovery_state: row.discovery_state ?? 'observed',
    first_seen_at: row.first_seen_at ?? null,
    last_seen_at: row.last_seen_at ?? null,
    observation_count: Number.isInteger(row.observation_count) ? row.observation_count : 0,
  };
}

function safeCapabilityOverview(summary) {
  if (!summary || typeof summary !== 'object') return {};
  return {
    capability_count: Number.isInteger(summary.capability_count) ? summary.capability_count : 0,
    installation_count: Number.isInteger(summary.installation_count) ? summary.installation_count : 0,
    by_kind: summary.by_kind && typeof summary.by_kind === 'object' && !Array.isArray(summary.by_kind)
      ? summary.by_kind
      : {},
    by_provider: summary.by_provider && typeof summary.by_provider === 'object' && !Array.isArray(summary.by_provider)
      ? summary.by_provider
      : {},
    sampled: summary.sampled === true,
  };
}

export async function listCapabilities({ provider, serverName, toolName, limit = 100, offset = 0 } = {}) {
  const result = await readRequest('/v1/capability-catalog', {
    provider,
    server_name: serverName,
    tool_name: toolName,
    limit,
    offset,
  });
  return {
    ...result,
    data: {
      ...result.data,
      items: (Array.isArray(result.data?.items) ? result.data.items : []).map(safeCapability),
    },
  };
}

export async function getCapabilityOverview() {
  const result = await readRequest('/v1/capability-catalog/overview');
  return { ...result, data: safeCapabilityOverview(result.data) };
}

export async function getCapability(capabilityId) {
  if (!CAPABILITY_ID_PATTERN.test(capabilityId)) {
    throw new Error('Capability IDs must have the form cap_ followed by 24 lowercase hexadecimal characters.');
  }
  const result = await readRequest(`/v1/capability-catalog/${encodeURIComponent(capabilityId)}`);
  return { ...result, data: safeCapability(result.data) };
}

function safeEntity(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return null;
  const entityId = row.entity_id;
  if (typeof entityId !== 'string' || !entityId.trim() || entityId.length > 256) return null;
  const entityType = typeof row.entity_type === 'string' && row.entity_type.length <= 64
    ? row.entity_type
    : 'unknown';
  const displayName = typeof row.display_name === 'string' && row.display_name.length <= 512
    ? row.display_name
    : '';
  return {
    entity_id: entityId,
    entity_type: entityType,
    display_name: displayName,
    parent_entity_id: typeof row.parent_entity_id === 'string'
      && row.parent_entity_id.length <= 256
      ? row.parent_entity_id
      : null,
    created_at: typeof row.created_at === 'string' && row.created_at.length <= 64
      ? row.created_at
      : null,
    updated_at: typeof row.updated_at === 'string' && row.updated_at.length <= 64
      ? row.updated_at
      : null,
  };
}

export async function listEntities({ entityType, limit = 25 } = {}, env = process.env) {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_ENTITY_PAGE_SIZE) {
    throw new Error(`Entity page size must be an integer from 1 through ${MAX_ENTITY_PAGE_SIZE}.`);
  }
  if (entityType !== undefined
      && (typeof entityType !== 'string' || !entityType.trim() || entityType.length > 64)) {
    throw new Error('Entity type filters must contain 1 through 64 characters.');
  }
  const result = await readRequest('/v1/entities', {
    entity_type: entityType?.trim(),
    limit,
  }, env);
  const rows = Array.isArray(result.data?.entities) ? result.data.entities.slice(0, limit) : [];
  const entities = rows.map(safeEntity).filter(Boolean);
  return {
    ...result,
    data: {
      entities,
      count: entities.length,
    },
  };
}

export async function getEntity(entityId, env = process.env) {
  if (typeof entityId !== 'string' || !entityId.trim() || entityId.length > 256) {
    throw new Error('Entity IDs must contain 1 through 256 characters.');
  }
  const result = await readRequest(`/v1/entities/${encodeURIComponent(entityId.trim())}`, undefined, env);
  const entity = safeEntity(result.data);
  if (!entity) {
    throw new AccessApiError('Aether API returned an unexpected entity response.', {
      requestId: result.requestId,
    });
  }
  return { ...result, data: entity };
}

export function buildTrackBatch({
  eventName,
  eventId,
  sessionId,
  anonymousId,
  eventSequence,
  properties = {},
  surface,
  now = new Date(),
}) {
  if (typeof eventName !== 'string' || !eventName.trim() || eventName.length > 128) {
    throw new Error('Event name must contain 1 through 128 characters.');
  }
  if (typeof eventId !== 'string' || !eventId.trim() || eventId.length > 128) {
    throw new Error('Event ID must contain 1 through 128 characters.');
  }
  for (const [name, value] of [['session ID', sessionId], ['anonymous ID', anonymousId]]) {
    if (typeof value !== 'string' || !value.trim() || value.length > 256) {
      throw new Error(`${name} must contain 1 through 256 characters.`);
    }
  }
  if (!Number.isSafeInteger(eventSequence) || eventSequence < 0) {
    throw new Error('Sequence must be a non-negative safe integer.');
  }
  if (!['cli', 'mcp'].includes(surface)) {
    throw new Error('Observation surface must be cli or mcp.');
  }
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) {
    throw new Error('Properties must be a JSON object.');
  }

  const timestamp = now.toISOString();
  const batch = {
    batch: [{
      id: eventId.trim(),
      type: 'track',
      timestamp,
      sessionId: sessionId.trim(),
      anonymousId: anonymousId.trim(),
      properties: { ...properties, event: eventName.trim() },
      context: {
        library: { name: '@aether/access-kit', version: '0.1.0-alpha.0' },
        surface,
        schemaVersion: '1.0.0',
        sequence: { event: eventSequence },
      },
    }],
    sentAt: timestamp,
  };
  if (Buffer.byteLength(JSON.stringify(batch), 'utf8') > MAX_INGEST_BODY_BYTES) {
    throw new Error(`Observation request exceeds the ${MAX_INGEST_BODY_BYTES}-byte client limit.`);
  }
  return batch;
}

export async function ingestTrackObservation(input, env = process.env) {
  const { apiOrigin, publishableKey, siteId } = readPublishableConfig(env);
  const body = buildTrackBatch(input);
  const correlationId = randomUUID();
  let response;
  try {
    response = await fetch(new URL('/v1/batch', `${apiOrigin}/`), {
      method: 'POST',
      redirect: 'error',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
        authorization: `Bearer ${publishableKey}`,
        'x-aether-site': siteId,
        'x-correlation-id': correlationId,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const reason = error?.name === 'TimeoutError' ? 'request timed out' : 'could not reach the Aether API';
    throw new AccessApiError(reason, { requestId: correlationId });
  }

  const requestId = response.headers.get('x-correlation-id')
    || response.headers.get('x-request-id')
    || correlationId;
  let result;
  try {
    result = await response.json();
  } catch {
    throw new AccessApiError(`Aether API returned a non-JSON response (HTTP ${response.status}).`, {
      status: response.status,
      requestId,
    });
  }
  if (!response.ok) {
    const errorCode = result?.error?.code ?? result?.code;
    const apiRequestId = typeof result?.meta?.request_id === 'string'
      ? result.meta.request_id
      : (typeof result?.request_id === 'string' ? result.request_id : undefined);
    throw new AccessApiError(
      `Aether API request failed (HTTP ${response.status}${errorCode ? `, ${errorCode}` : ''}).`,
      { status: response.status, code: errorCode, requestId, apiRequestId },
    );
  }
  return {
    data: result,
    requestId,
    responseRequestId: typeof result?.meta?.request_id === 'string' ? result.meta.request_id : undefined,
  };
}

export function validateReadConfig(env = process.env) {
  readConfig(env);
}

export function validateIngestConfig(env = process.env) {
  readPublishableConfig(env);
}
