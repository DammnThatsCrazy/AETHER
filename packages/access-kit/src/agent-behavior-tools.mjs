import * as z from 'zod/v4';

import { AccessApiError, getAgentBehavior, getAgentDecision } from './api.mjs';
import { interactionSchema } from './interaction-schema.mjs';

const agentRefSchema = z.string().trim().min(1).max(256);

const requestIdsSchema = {
  request_id: z.string(),
  api_request_id: z.string().optional(),
  interaction: interactionSchema,
};

function requestIds(result) {
  return {
    request_id: result.requestId,
    ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
    interaction: result.interaction,
  };
}

function toolResult(output) {
  return { content: [{ type: 'text', text: JSON.stringify(output) }], structuredContent: output };
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
    : { message: 'The Aether API operation could not be completed.' };
  return { content: [{ type: 'text', text: JSON.stringify({ error: details }) }], isError: true };
}

/**
 * Agent behavior reads (WO-123). Both routes require the server-side
 * ``agent:manage`` permission; the read models are backend-owned and carry
 * their own evidence and epistemic state, which these tools pass through.
 */
export function registerAgentBehaviorTools(
  server,
  { behavior = getAgentBehavior, decision = getAgentDecision } = {},
) {
  server.registerTool(
    'agents_behavior',
    {
      title: 'Read an agent behavior read model',
      description: 'Read the Agent360 behavior read model for one source-reported agent ref through GET /v1/agent/agents/{agent_ref}/behavior. Every section states available, partial, or unavailable and keeps its evidence; inferred behavior is never verified fact and the agent ref is not an identity resolution. The API requires agent:manage and decides tenant scope.',
      inputSchema: z.object({ agent_ref: agentRefSchema }).strict(),
      outputSchema: z.object({
        behavior: z.record(z.string(), z.unknown()),
        ...requestIdsSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ agent_ref }) => {
      try {
        const result = await behavior(agent_ref);
        return toolResult({ behavior: result.data, ...requestIds(result) });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    'agents_decision',
    {
      title: 'Read one reconstructed agent decision',
      description: 'Read one reconstructed decision envelope with attribution, responsibility roles, and a labelled counterfactual through GET /v1/agent/agents/{agent_ref}/decisions/{decision_id}. A decision owned by another agent or tenant is not found. The API requires agent:manage.',
      inputSchema: z.object({
        agent_ref: agentRefSchema,
        decision_id: z.string().trim().min(1).max(256),
      }).strict(),
      outputSchema: z.object({
        decision: z.record(z.string(), z.unknown()),
        ...requestIdsSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ agent_ref, decision_id }) => {
      try {
        const result = await decision(agent_ref, decision_id);
        return toolResult({ decision: result.data, ...requestIds(result) });
      } catch (error) {
        return toolError(error);
      }
    },
  );
}
