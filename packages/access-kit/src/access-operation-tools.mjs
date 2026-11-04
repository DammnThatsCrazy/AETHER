import * as z from 'zod/v4';

import { AccessApiError } from './api.mjs';
import {
  accessOperationIds,
  invokeAccessOperation,
  listAccessOperations,
  SERVER_PERMISSIONS,
} from './access-operations.mjs';
import { interactionSchema } from './interaction-schema.mjs';

const operationDescriptor = z.object({
  id: z.string(),
  description: z.string(),
  operation: z.literal('query'),
  required_server_permission: z.enum(SERVER_PERMISSIONS),
  api: z.string(),
  owner: z.string(),
  cli: z.string(),
  mcp: z.string().nullable(),
  mcp_invoke: z.literal('access_invoke_read'),
  authorization: z.literal('server_decides_per_request'),
});

function errorResult(error) {
  const details = error instanceof AccessApiError
    ? {
      message: error.message,
      ...(Number.isInteger(error.status) ? { status: error.status } : {}),
      ...(error.code ? { code: error.code } : {}),
      ...(error.requestId ? { request_id: error.requestId } : {}),
      ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
      ...(error.interaction ? { interaction: error.interaction } : {}),
    }
    : { message: 'The Access Kit operation could not be completed.' };
  return { content: [{ type: 'text', text: JSON.stringify({ error: details }) }], isError: true };
}

function toolResult(output) {
  return {
    content: [{ type: 'text', text: JSON.stringify(output) }],
    structuredContent: output,
  };
}

export function registerAccessOperationTools(server, env = process.env) {
  server.registerTool(
    'access_operations_list',
    {
      title: 'List supported Access Kit read operations',
      description: 'List this adapter’s closed set of supported read operations. This static list is not a tenant grant or an Aether server capability registry; the owning API authorizes every invocation.',
      inputSchema: z.object({}).strict(),
      outputSchema: z.object({
        catalog_kind: z.literal('adapter_supported_operations'),
        operations: z.array(operationDescriptor).max(50),
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => toolResult({
      catalog_kind: 'adapter_supported_operations',
      operations: listAccessOperations(),
    }),
  );

  server.registerTool(
    'access_invoke_read',
    {
      title: 'Invoke a supported Access Kit read',
      description: 'Invoke one closed-list read operation through its owning Aether tenant API. Operation metadata is adapter support only; it does not grant access. The server resolves tenant and actor, checks the operation’s declared required_server_permission, and returns the authoritative result and interaction references.',
      inputSchema: z.object({
        operation_id: z.enum(accessOperationIds),
        input: z.record(z.string(), z.unknown()).optional(),
      }).strict(),
      outputSchema: z.object({
        operation_id: z.enum(accessOperationIds),
        data: z.record(z.string(), z.unknown()),
        request_id: z.string(),
        api_request_id: z.string().optional(),
        interaction: interactionSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ operation_id, input }) => {
      try {
        const result = await invokeAccessOperation(operation_id, input ?? {}, env);
        return toolResult({
          operation_id,
          data: result.data,
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        });
      } catch (error) {
        return errorResult(error);
      }
    },
  );
}
