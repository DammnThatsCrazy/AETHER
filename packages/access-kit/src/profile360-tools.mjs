import * as z from 'zod/v4';

import { AccessApiError } from './api.mjs';
import { invokeAccessOperation } from './access-operations.mjs';
import { interactionSchema } from './interaction-schema.mjs';
import {
  profile360EvidenceGetInput,
  profile360GetInput,
  profile360SearchInput,
  profile360SlotGetInput,
} from './profile360.mjs';

// Named Profile360 MCP tools. Each delegates to the closed Access Kit
// operation table, so a named tool and access_invoke_read behave identically:
// same bounded input, same owning route, same server authorization.

const TOOLS = [
  {
    name: 'profile360_search',
    operation: 'profile360.search',
    title: 'Find a Profile360 entity by identifier',
    description: 'Resolve exactly one identifier (email, wallet, device, session, social or customer) to the canonical entity ID for this tenant. Use the returned entity_id with profile360_get. Returns 404 when nothing resolves; never guesses.',
    input: profile360SearchInput,
  },
  {
    name: 'profile360_get',
    operation: 'profile360.get',
    title: 'Read a Profile360 frame',
    description: 'Read the governed Profile360 frame for one entity: identity, sessions, journeys, delegations, communications, relationships, value, risk, location and predictions. Each slot carries its server-reported state, a freshness verdict (fresh, stale or unknown) and evidence. Partial, unknown and suppressed slots are returned as-is and must not be read as complete.',
    input: profile360GetInput,
  },
  {
    name: 'profile360_slot_get',
    operation: 'profile360.slot.get',
    title: 'Read selected Profile360 slots',
    description: 'Read up to 8 named Profile360 slots with evidence (for example risk_summary, value_summary, relationships). Cheaper than a full frame when only a few facets are needed.',
    input: profile360SlotGetInput,
  },
  {
    name: 'profile360_evidence_get',
    operation: 'profile360.evidence.get',
    title: 'Read Profile360 evidence',
    description: 'Read the evidence trace behind a Profile360 frame or selected slots: evidence references, provenance, claim evidence, freshness and reason codes. Slot content is omitted; use it to audit or cite a profile claim.',
    input: profile360EvidenceGetInput,
  },
];

export const PROFILE360_TOOL_NAMES = Object.freeze(TOOLS.map(({ name }) => name));

function toolError(error) {
  const details = error instanceof AccessApiError
    ? {
      message: error.message,
      ...(Number.isInteger(error.status) ? { status: error.status } : {}),
      ...(error.code ? { code: error.code } : {}),
      ...(Number.isInteger(error.retryAfterSeconds) ? { retry_after_seconds: error.retryAfterSeconds } : {}),
      ...(error.requestId ? { request_id: error.requestId } : {}),
      ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
      ...(error.interaction ? { interaction: error.interaction } : {}),
    }
    : { message: error instanceof Error && error.message.startsWith('Invalid input')
      ? error.message
      : 'The Profile360 read could not be completed.' };
  return { content: [{ type: 'text', text: JSON.stringify({ error: details }) }], isError: true };
}

export function registerProfile360Tools(server, env = process.env, { invoke = invokeAccessOperation } = {}) {
  for (const tool of TOOLS) {
    server.registerTool(
      tool.name,
      {
        title: tool.title,
        description: tool.description,
        inputSchema: tool.input,
        outputSchema: z.object({
          operation_id: z.literal(tool.operation),
          data: z.record(z.string(), z.unknown()),
          request_id: z.string(),
          api_request_id: z.string().optional(),
          interaction: interactionSchema,
        }),
        annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
      },
      async (input) => {
        try {
          const result = await invoke(tool.operation, input ?? {}, env);
          const output = {
            operation_id: tool.operation,
            data: result.data,
            request_id: result.requestId,
            ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
            interaction: result.interaction,
          };
          return { content: [{ type: 'text', text: JSON.stringify(output) }], structuredContent: output };
        } catch (error) {
          return toolError(error);
        }
      },
    );
  }
}
