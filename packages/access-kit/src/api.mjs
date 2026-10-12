import { randomUUID } from 'node:crypto';
import { normalizeInteractionOutcome } from './interaction.mjs';

const DEFAULT_API_URL = 'https://api.aether.io';
const REQUEST_TIMEOUT_MS = 15_000;
const CAPABILITY_ID_PATTERN = /^cap_[a-f0-9]{24}$/;
const SITE_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_INGEST_BODY_BYTES = 64 * 1024;
export const MAX_ENTITY_PAGE_SIZE = 50;
export const MAX_OVERVIEW_BUCKETS = 50;
const ACCESS_SURFACES = new Set(['cli', 'mcp_stdio', 'mcp_http']);

export class AccessApiError extends Error {
  constructor(message, { status, code, requestId, apiRequestId, interaction } = {}) {
    super(message);
    this.name = 'AccessApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.apiRequestId = apiRequestId;
    this.interaction = interaction;
  }
}

function isLoopback(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  return normalized === 'localhost'
    || normalized === '127.0.0.1'
    || normalized === '::1';
}

export function readApiOrigin(env = process.env) {
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
  const apiKey = typeof env.AETHER_API_KEY === 'string' && env.AETHER_API_KEY.trim()
    ? env.AETHER_API_KEY
    : undefined;
  const sessionToken = typeof env.AETHER_SESSION_TOKEN === 'string' && env.AETHER_SESSION_TOKEN.trim()
    ? env.AETHER_SESSION_TOKEN
    : undefined;
  if (apiKey && sessionToken) {
    throw new Error('Set only one read credential: AETHER_API_KEY or AETHER_SESSION_TOKEN.');
  }
  if (!apiKey && !sessionToken) {
    throw new Error('Set AETHER_API_KEY or AETHER_SESSION_TOKEN for a tenant-scoped API request.');
  }

  const authHeaders = apiKey
    ? { authorization: `Bearer ${apiKey}` }
    : { 'x-session-token': sessionToken };
  return { apiOrigin, authHeaders };
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

async function readRequest(
  path,
  query = undefined,
  env = process.env,
  { method = 'GET', operation = 'query' } = {},
) {
  const { apiOrigin, authHeaders } = readConfig(env);
  const url = new URL(path, `${apiOrigin}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
    }
  }

  const correlationId = randomUUID();
  const surface = ACCESS_SURFACES.has(env.AETHER_ACCESS_SURFACE)
    ? env.AETHER_ACCESS_SURFACE
    : undefined;
  let response;
  try {
    response = await fetch(url, {
      method,
      redirect: 'error',
      headers: {
        accept: 'application/json',
        ...authHeaders,
        'x-correlation-id': correlationId,
        ...(surface ? { 'x-aether-access-surface': surface } : {}),
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const reason = error?.name === 'TimeoutError' ? 'request timed out' : 'could not reach the Aether API';
    throw new AccessApiError(reason, {
      requestId: correlationId,
      interaction: normalizeInteractionOutcome({ operation, requestId: correlationId }),
    });
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
      interaction: normalizeInteractionOutcome({
        operation, httpStatus: response.status, requestId: headerRequestId,
        responseOk: false, contractError: true,
      }),
    });
  }

  const apiRequestId = typeof payload?.meta?.request_id === 'string'
    ? payload.meta.request_id
    : (typeof payload?.request_id === 'string' ? payload.request_id : undefined);
  const interactionData = {
    ...(payload?.data && typeof payload.data === 'object' && !Array.isArray(payload.data)
      ? payload.data
      : {}),
    ...(response.headers.get('x-aether-audit-event-id')
      ? { audit_event_id: response.headers.get('x-aether-audit-event-id') }
      : {}),
    ...(response.headers.get('x-aether-usage-event-id')
      ? { usage_event_id: response.headers.get('x-aether-usage-event-id') }
      : {}),
  };
  if (!response.ok) {
    const errorCode = payload?.error?.code ?? payload?.code;
    throw new AccessApiError(
      `Aether API request failed (HTTP ${response.status}${errorCode ? `, ${errorCode}` : ''}).`,
      {
        status: response.status, code: errorCode, requestId: headerRequestId, apiRequestId,
        interaction: normalizeInteractionOutcome({
          operation, httpStatus: response.status, requestId: headerRequestId,
          apiRequestId, responseOk: false, code: errorCode, data: interactionData,
        }),
      },
    );
  }

  if (!payload || typeof payload !== 'object' || Array.isArray(payload)
      || !Object.hasOwn(payload, 'data') || !payload.data || typeof payload.data !== 'object'
      || Array.isArray(payload.data)) {
    throw new AccessApiError('Aether API returned an unexpected response envelope.', {
      status: response.status,
      requestId: headerRequestId,
      apiRequestId,
      interaction: normalizeInteractionOutcome({
        operation, httpStatus: response.status, requestId: headerRequestId,
        apiRequestId, responseOk: true, contractError: true, data: interactionData,
      }),
    });
  }

  const responseRequestId = apiRequestId;
  return {
    data: payload.data,
    requestId: headerRequestId,
    responseRequestId,
    interaction: normalizeInteractionOutcome({
      operation, httpStatus: response.status, requestId: headerRequestId,
      apiRequestId: responseRequestId, responseOk: true, data: interactionData,
    }),
  };
}

function boundedString(value, maxLength = 256) {
  return typeof value === 'string' && value.length <= maxLength ? value : null;
}

function safeAccountContext(profile) {
  const plan = profile?.plan;
  const billing = profile?.billing;
  return {
    name: boundedString(profile?.name, 256),
    plan: plan && typeof plan === 'object' ? {
      plan_id: boundedString(plan.plan_id, 128),
      display_name: boundedString(plan.display_name, 128),
      monthly_quota: Number.isSafeInteger(plan.monthly_quota) && plan.monthly_quota >= 0
        ? plan.monthly_quota
        : null,
      burst_rpm: Number.isSafeInteger(plan.burst_rpm) && plan.burst_rpm >= 0
        ? plan.burst_rpm
        : null,
    } : null,
    billing: billing && typeof billing === 'object' ? {
      subscription_status: boundedString(billing.subscription_status, 64),
      current_period_end: boundedString(billing.current_period_end, 64),
    } : null,
    api_key_count: Number.isSafeInteger(profile?.api_key_count) && profile.api_key_count >= 0
      ? profile.api_key_count
      : null,
    is_admin: typeof profile?.is_admin === 'boolean' ? profile.is_admin : null,
  };
}

export async function getAccountContext(env = process.env) {
  const result = await readRequest('/v1/me', undefined, env);
  return { ...result, data: safeAccountContext(result.data) };
}

function safeUsageSummary(summary) {
  const usage = summary?.usage_by_dimension;
  const count = usage && typeof usage === 'object' && !Array.isArray(usage)
    && Number.isFinite(usage.access_interaction)
    && usage.access_interaction >= 0
    ? usage.access_interaction
    : 0;
  return {
    access_interaction_count: count,
    billing_period_start: boundedString(summary?.billing_period_start, 64),
    billing_period_end: boundedString(summary?.billing_period_end, 64),
    status: ['available', 'truncated'].includes(summary?.status) ? summary.status : 'unavailable',
  };
}

export async function getUsageSummary(env = process.env) {
  const result = await readRequest('/v1/billing/usage/summary', undefined, env);
  return { ...result, data: safeUsageSummary(result.data) };
}

const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_SESSION_PAGE_SIZE = 100;
const MAX_SESSION_OFFSET = 10_000;

function safeSession(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return null;
  const sessionId = boundedString(row.session_id ?? row.id, 128);
  if (!sessionId || !SESSION_ID_PATTERN.test(sessionId)) return null;
  return {
    session_id: sessionId,
    status: boundedString(row.status, 32),
    credential_class: boundedString(row.credential_class, 64),
    idle_expires_at: boundedString(row.idle_expires_at, 64),
    absolute_expires_at: boundedString(row.absolute_expires_at, 64),
  };
}

export async function listSessions({ limit = 20, offset = 0 } = {}, env = process.env) {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_SESSION_PAGE_SIZE) {
    throw new Error(`Session page size must be an integer from 1 through ${MAX_SESSION_PAGE_SIZE}.`);
  }
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > MAX_SESSION_OFFSET) {
    throw new Error(`Session offset must be an integer from 0 through ${MAX_SESSION_OFFSET}.`);
  }
  const result = await readRequest('/v1/me/sessions', { limit, offset }, env, { operation: 'auth' });
  const rows = Array.isArray(result.data?.sessions) ? result.data.sessions.slice(0, limit) : [];
  const sessions = rows.map(safeSession).filter(Boolean);
  return {
    ...result,
    data: {
      sessions,
      count: sessions.length,
      total: Number.isSafeInteger(result.data?.total) && result.data.total >= 0
        ? result.data.total
        : sessions.length,
      limit,
      offset,
    },
  };
}

export async function revokeSession(sessionId, env = process.env) {
  if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) {
    throw new Error('Session IDs must contain 1 through 128 letters, digits, underscores, or hyphens.');
  }
  const result = await readRequest(
    `/v1/me/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    env,
    { method: 'DELETE', operation: 'auth' },
  );
  return {
    ...result,
    data: {
      revoked: result.data?.revoked === true,
      session_id: boundedString(result.data?.id, 128) ?? sessionId,
    },
  };
}

function boundedText(value, maxLength) {
  return typeof value === 'string' && value.length <= maxLength ? value : null;
}

function nonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

export function projectObservedCapability(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)
      || typeof row.capability_id !== 'string'
      || !CAPABILITY_ID_PATTERN.test(row.capability_id)) return null;
  return {
    capability_id: row.capability_id,
    capability_kind: boundedText(row.capability_kind, 64) ?? 'unknown',
    provider: boundedText(row.provider, 128),
    server_name: boundedText(row.server_name, 128),
    tool_name: boundedText(row.tool_name, 128),
    protocol_version: boundedText(row.protocol_version, 64),
    latest_risk_level: boundedText(row.latest_risk_level, 64),
    discovery_state: boundedText(row.discovery_state, 64) ?? 'observed',
    first_seen_at: boundedText(row.first_seen_at, 64),
    last_seen_at: boundedText(row.last_seen_at, 64),
    observation_count: nonNegativeInteger(row.observation_count),
  };
}

function projectBuckets(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { buckets: {}, truncated: false };
  }
  const entries = [];
  let validEntryCount = 0;
  for (const [key, count] of Object.entries(value)) {
    if (key.length === 0 || key.length > 64 || !Number.isSafeInteger(count) || count < 0) continue;
    validEntryCount += 1;
    if (entries.length < MAX_OVERVIEW_BUCKETS) entries.push([key, count]);
  }
  return { buckets: Object.fromEntries(entries), truncated: validEntryCount > MAX_OVERVIEW_BUCKETS };
}

export function projectObservedCapabilityOverview(summary) {
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) {
    return { capability_count: 0, installation_count: 0, by_kind: {}, by_provider: {}, sampled: false };
  }
  const byKind = projectBuckets(summary.by_kind);
  const byProvider = projectBuckets(summary.by_provider);
  return {
    capability_count: nonNegativeInteger(summary.capability_count),
    installation_count: nonNegativeInteger(summary.installation_count),
    by_kind: byKind.buckets,
    by_provider: byProvider.buckets,
    sampled: summary.sampled === true || byKind.truncated || byProvider.truncated,
  };
}

export async function listCapabilities(
  { provider, serverName, toolName, limit = 100, offset = 0 } = {},
  env = process.env,
) {
  const result = await readRequest('/v1/capability-catalog', {
    provider,
    server_name: serverName,
    tool_name: toolName,
    limit,
    offset,
  }, env);
  const items = (Array.isArray(result.data?.items) ? result.data.items : [])
    .map(projectObservedCapability)
    .filter(Boolean);
  return { ...result, data: { items, count: items.length } };
}

export async function getCapabilityOverview(env = process.env) {
  const result = await readRequest('/v1/capability-catalog/overview', undefined, env);
  return { ...result, data: projectObservedCapabilityOverview(result.data) };
}

export async function getCapability(capabilityId, env = process.env) {
  if (!CAPABILITY_ID_PATTERN.test(capabilityId)) {
    throw new Error('Capability IDs must have the form cap_ followed by 24 lowercase hexadecimal characters.');
  }
  const result = await readRequest(`/v1/capability-catalog/${encodeURIComponent(capabilityId)}`, undefined, env);
  const capability = projectObservedCapability(result.data);
  if (!capability) {
    throw new AccessApiError('Aether API returned an unexpected capability response.', {
      requestId: result.requestId,
      apiRequestId: result.responseRequestId,
      interaction: normalizeInteractionOutcome({
        operation: 'query', httpStatus: result.interaction.http_status,
        requestId: result.requestId, apiRequestId: result.responseRequestId,
        responseOk: true, contractError: true,
      }),
    });
  }
  return { ...result, data: capability };
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
      apiRequestId: result.responseRequestId,
      interaction: normalizeInteractionOutcome({
        operation: 'query', requestId: result.requestId,
        httpStatus: result.interaction.http_status, responseOk: true, contractError: true,
        apiRequestId: result.responseRequestId,
      }),
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
    throw new AccessApiError(reason, {
      requestId: correlationId,
      interaction: normalizeInteractionOutcome({ operation: 'observe', requestId: correlationId }),
    });
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
      interaction: normalizeInteractionOutcome({
        operation: 'observe', httpStatus: response.status, requestId,
        responseOk: false, contractError: true,
      }),
    });
  }
  const apiRequestId = typeof result?.meta?.request_id === 'string'
    ? result.meta.request_id
    : (typeof result?.request_id === 'string' ? result.request_id : undefined);
  if (!response.ok) {
    const errorCode = result?.error?.code ?? result?.code;
    throw new AccessApiError(
      `Aether API request failed (HTTP ${response.status}${errorCode ? `, ${errorCode}` : ''}).`,
      {
        status: response.status, code: errorCode, requestId, apiRequestId,
        interaction: normalizeInteractionOutcome({
          operation: 'observe', httpStatus: response.status, requestId, apiRequestId,
          responseOk: false, code: errorCode,
        }),
      },
    );
  }
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new AccessApiError('Aether API returned an unexpected ingestion response.', {
      status: response.status,
      requestId,
      apiRequestId,
      interaction: normalizeInteractionOutcome({
        operation: 'observe', httpStatus: response.status, requestId, apiRequestId,
        responseOk: true, contractError: true,
      }),
    });
  }
  const responseRequestId = apiRequestId;
  return {
    data: result,
    requestId,
    responseRequestId,
    interaction: normalizeInteractionOutcome({
      operation: 'observe', httpStatus: response.status, requestId,
      apiRequestId: responseRequestId, responseOk: true, data: result,
    }),
  };
}

export function validateReadConfig(env = process.env) {
  readConfig(env);
}

export function validateIngestConfig(env = process.env) {
  readPublishableConfig(env);
}
