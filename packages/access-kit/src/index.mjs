import { readConfig } from './api.mjs';
import {
  getAccessOperation,
  invokeAccessOperation,
  listAccessOperations,
} from './access-operations.mjs';
import { createContinuation, getContinuation } from './continuation.mjs';

/**
 * Create an Access Kit client. The API remains the tenant, permission,
 * billing, and data authority; this client never accepts a tenant override.
 */
export function createAccessClient({ apiUrl, apiKey, sessionToken } = {}) {
  const env = {
    ...(apiUrl ? { AETHER_API_URL: apiUrl } : {}),
    ...(apiKey ? { AETHER_API_KEY: apiKey } : {}),
    ...(sessionToken ? { AETHER_SESSION_TOKEN: sessionToken } : {}),
    AETHER_ACCESS_SURFACE: 'access_sdk',
  };
  readConfig(env);

  async function invoke(operationId, input = {}) {
    const result = await invokeAccessOperation(operationId, input, env);
    return {
      data: result.data,
      request_id: result.requestId,
      ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
      interaction: result.interaction,
    };
  }

  return Object.freeze({
    operations: Object.freeze({
      list: () => listAccessOperations(),
      show: (id) => getAccessOperation(id),
      invoke,
    }),
    account: Object.freeze({ context: () => invoke('account.context') }),
    entities: Object.freeze({
      list: (input = {}) => invoke('entities.list', input),
      get: (entityId) => invoke('entities.get', { entity_id: entityId }),
      neighborhood: (entityId, input = {}) => invoke('entities.neighborhood', {
        ...input,
        entity_id: entityId,
      }),
    }),
    observedAccess: Object.freeze({
      list: (input = {}) => invoke('agent_access.observed.list', input),
      overview: () => invoke('agent_access.observed.overview'),
      get: (capabilityId) => invoke('agent_access.observed.get', { capability_id: capabilityId }),
    }),
    agents: Object.freeze({
      behavior: (agentRef) => invoke('agents.behavior', { agent_ref: agentRef }),
      decision: (agentRef, decisionId) => invoke('agents.decision', {
        agent_ref: agentRef, decision_id: decisionId,
      }),
    }),
    usage: Object.freeze({ summary: () => invoke('usage.summary') }),
    continuations: Object.freeze({
      create: async (input) => {
        const result = await createContinuation(input, env, { sourceClient: 'agent' });
        return {
          data: result.data,
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        };
      },
      get: async (continuationId) => {
        const result = await getContinuation(continuationId, env);
        return {
          data: result.data,
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        };
      },
    }),
  });
}

export { getAccessOperation, listAccessOperations };
