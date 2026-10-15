import { AccessApiError, readConfig, requestAether } from './api.mjs';
import { normalizeInteractionOutcome } from './interaction.mjs';

const CONTINUATION_ID_PATTERN = /^cont_[a-f0-9]{32}$/;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

function boundedText(value, maxLength) {
  return typeof value === 'string' && value.length <= maxLength ? value : null;
}

function contractError(result, operation) {
  return new AccessApiError('Aether API returned an unexpected continuation response.', {
    requestId: result.requestId,
    apiRequestId: result.responseRequestId,
    interaction: normalizeInteractionOutcome({
      operation,
      httpStatus: result.interaction?.http_status,
      requestId: result.requestId,
      apiRequestId: result.responseRequestId,
      responseOk: true,
      contractError: true,
    }),
  });
}

function projectContinuation(result, { created = false } = {}) {
  const row = result.data;
  if (!row || typeof row !== 'object' || Array.isArray(row)
      || typeof row.id !== 'string' || !CONTINUATION_ID_PATTERN.test(row.id)
      || !row.summary || typeof row.summary !== 'object'
      || typeof row.summary.title !== 'string'
      || !Number.isSafeInteger(row.state_revision) || row.state_revision < 0
      || !Array.isArray(row.resource_references)
      || (created && typeof row.replayed !== 'boolean')) {
    throw contractError(result, created ? 'write' : 'query');
  }
  const entityIds = row.resource_references
    .filter((reference) => reference && typeof reference === 'object'
      && reference.kind === 'entity'
      && typeof reference.id === 'string'
      && reference.id.length > 0 && reference.id.length <= 256)
    .slice(0, 5).map((reference) => reference.id);
  const projection = {
    continuation_id: row.id,
    title: boundedText(row.summary.title, 120) ?? row.summary.title.slice(0, 120),
    title_truncated: row.summary.title.length > 120,
    entity_ids: entityIds,
    references_truncated: entityIds.length !== row.resource_references.length,
    state_revision: row.state_revision,
    updated_at: boundedText(row.updated_at, 64),
    ...(created ? { replayed: row.replayed } : {}),
  };
  return {
    ...result,
    data: projection,
    interaction: {
      ...result.interaction,
      references: {
        ...result.interaction.references,
        continuation_id: row.id,
      },
    },
  };
}

export function validateContinuationId(continuationId) {
  if (typeof continuationId !== 'string' || !CONTINUATION_ID_PATTERN.test(continuationId)) {
    throw new Error('Continuation ID must have the form cont_ followed by 32 lowercase hexadecimal characters.');
  }
  return continuationId;
}

export async function createContinuation(
  { title, entityId, idempotencyKey }, env = process.env, { sourceClient = 'agent' } = {},
) {
  if (typeof env.AETHER_MCP_OAUTH_TOKEN === 'string' && env.AETHER_MCP_OAUTH_TOKEN.trim()) {
    throw new Error('Delegated MCP read tokens cannot create continuations.');
  }
  readConfig(env);
  if (typeof title !== 'string' || !title.trim() || title.trim().length > 120) {
    throw new Error('Continuation title must contain 1 through 120 characters.');
  }
  if (typeof entityId !== 'string' || !entityId.trim() || entityId.trim().length > 256) {
    throw new Error('Continuation entity ID must contain 1 through 256 characters.');
  }
  if (typeof idempotencyKey !== 'string' || !IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
    throw new Error('Continuation idempotency key must contain 1 through 128 letters, digits, dots, underscores, colons, or hyphens.');
  }
  if (!['agent', 'desktop'].includes(sourceClient)) {
    throw new Error('Unsupported continuation source client.');
  }
  const result = await requestAether(
    '/v1/continuations',
    { idempotency_key: idempotencyKey },
    env,
    {
      method: 'POST',
      operation: 'write',
      body: {
        source_client: sourceClient,
        surface: 'graph',
        summary: { title: title.trim() },
        resource_references: [{ kind: 'entity', id: entityId.trim() }],
      },
    },
  );
  return projectContinuation(result, { created: true });
}

export async function getContinuation(continuationId, env = process.env) {
  validateContinuationId(continuationId);
  const result = await requestAether(
    `/v1/continuations/${encodeURIComponent(continuationId)}`, undefined, env,
  );
  return projectContinuation(result);
}
