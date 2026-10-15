import * as z from 'zod/v4';

import { AccessApiError, getAccountContext } from './api.mjs';
import { accountContextSchema, interactionSchema } from './interaction-schema.mjs';

export function registerAccountContextTool(server, { get = getAccountContext } = {}) {
  server.registerTool(
    'account_context',
    {
      title: 'Read account context',
      description: 'Read the authenticated account name, plan limits, billing status, API key count, and caller admin flag. Uses the existing read-protected /v1/me route; tenant identity comes only from one explicit AETHER_API_KEY or AETHER_SESSION_TOKEN, or the local OS credential store after aether auth login. Omits tenant and graph IDs, contact email, and payment-provider IDs. This is account context, not a readiness or diagnostic assessment.',
      inputSchema: z.object({}).strict(),
      outputSchema: z.object({
        account: accountContextSchema,
        request_id: z.string(),
        api_request_id: z.string().optional(),
        interaction: interactionSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const result = await get();
        const output = {
          account: result.data,
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        const details = error instanceof AccessApiError
          ? {
            message: error.message,
            ...(Number.isInteger(error.status) ? { status: error.status } : {}),
            ...(error.code ? { code: error.code } : {}),
            ...(error.requestId ? { request_id: error.requestId } : {}),
            ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
            ...(error.interaction ? { interaction: error.interaction } : {}),
          }
          : { message: 'The Aether API operation could not be completed.' };
        return {
          content: [{ type: 'text', text: JSON.stringify({ error: details }) }],
          isError: true,
        };
      }
    },
  );
}
