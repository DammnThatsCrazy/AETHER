import * as z from 'zod/v4';

import { AccessApiError } from './api.mjs';
import { createContinuation, getContinuation } from './continuation.mjs';
import { interactionSchema } from './interaction-schema.mjs';

const handleSchema = {
  continuation_id: z.string().regex(/^cont_[a-f0-9]{32}$/),
  title: z.string().max(120),
  title_truncated: z.boolean(),
  entity_ids: z.array(z.string().max(256)).max(5),
  references_truncated: z.boolean(),
  state_revision: z.number().int().nonnegative(),
  updated_at: z.string().max(64).nullable(),
};

const resultSchema = {
  ...handleSchema,
  request_id: z.string(),
  api_request_id: z.string().optional(),
  interaction: interactionSchema,
};

function toolResult(result) {
  const output = {
    ...result.data,
    request_id: result.requestId,
    ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
    interaction: result.interaction,
  };
  return {
    content: [{ type: 'text', text: JSON.stringify(output) }],
    structuredContent: output,
  };
}

function toolError(error) {
  const details = error instanceof AccessApiError
    ? {
      message: error.message,
      ...(Number.isInteger(error.status) ? { status: error.status } : {}),
      ...(error.code ? { code: error.code } : {}),
      ...(error.requestId ? { request_id: error.requestId } : {}),
      ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
      ...(error.interaction ? { interaction: error.interaction } : {}),
    }
    : { message: 'The continuation operation could not be completed.' };
  return { content: [{ type: 'text', text: JSON.stringify({ error: details }) }], isError: true };
}

export function registerContinuationTools(server, env = process.env) {
  server.registerTool(
    'continuations_create',
    {
      title: 'Save an entity continuation',
      description: 'Create a tenant-owned, principal-owned continuation for one entity. This is a governed state write through /v1/continuations, not an external action. Requires server write permission and a caller-stable idempotency key; returns a durable handle and replay marker.',
      inputSchema: z.object({
        title: z.string().trim().min(1).max(120),
        entity_id: z.string().trim().min(1).max(256),
        idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
      }).strict(),
      outputSchema: z.object({ ...resultSchema, replayed: z.boolean() }),
      annotations: {
        readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false,
      },
    },
    async ({ title, entity_id, idempotency_key }) => {
      try {
        return toolResult(await createContinuation({
          title, entityId: entity_id, idempotencyKey: idempotency_key,
        }, env, { sourceClient: 'agent' }));
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    'continuations_get',
    {
      title: 'Read a saved continuation',
      description: 'Read back a continuation owned by the authenticated tenant principal. Returns only a bounded title, entity references, state revision, and server request evidence.',
      inputSchema: z.object({
        continuation_id: z.string().regex(/^cont_[a-f0-9]{32}$/),
      }).strict(),
      outputSchema: z.object(resultSchema),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ continuation_id }) => {
      try {
        return toolResult(await getContinuation(continuation_id, env));
      } catch (error) {
        return toolError(error);
      }
    },
  );
}
