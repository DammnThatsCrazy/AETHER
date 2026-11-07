import * as z from 'zod/v4';

import {
  getAccountContext,
  getAgentBehavior,
  getAgentDecision,
  getCapability,
  getCapabilityOverview,
  getEntity,
  getEntityNeighborhood,
  getUsageSummary,
  listCapabilities,
  listEntities,
} from './api.mjs';

// This is the Access Kit adapter's closed dispatch table. It describes calls
// this package can make; it is not a tenant grant or an Aether server registry.
// Every handler delegates to the owning tenant API, which resolves the caller
// and makes the authorization and data decisions on each request.
// ``required_server_permission`` declares the permission the owning API checks
// (default ``read``); it is documentation of that check, never a grant.
export const DEFAULT_SERVER_PERMISSION = 'read';
export const SERVER_PERMISSIONS = Object.freeze(['read', 'agent:manage']);

const agentRef = z.string().trim().min(1).max(256);

const definitions = [
  {
    id: 'account.context',
    description: 'Read the authenticated account context.',
    api: 'GET /v1/me',
    owner: 'tenancy',
    cli: 'aether account context',
    mcp: 'account_context',
    input: z.object({}).strict(),
    call: (_input, env) => getAccountContext(env),
  },
  {
    id: 'entities.list',
    description: 'Read a bounded tenant entity page; explicit offset uses stable ordering.',
    api: 'GET /v1/entities',
    owner: 'identity',
    cli: 'aether entities list',
    mcp: 'entities_list',
    input: z.object({
      entity_type: z.string().trim().min(1).max(64).optional(),
      limit: z.number().int().min(1).max(50).optional(),
      offset: z.number().int().min(0).max(100_000).optional(),
    }).strict(),
    call: ({ entity_type, limit, offset }, env) => listEntities({ entityType: entity_type, limit, offset }, env),
  },
  {
    id: 'entities.get',
    description: 'Read one entity through the tenant identity API.',
    api: 'GET /v1/entities/{entity_id}',
    owner: 'identity',
    cli: 'aether entities show',
    mcp: 'entities_get',
    input: z.object({ entity_id: z.string().trim().min(1).max(256) }).strict(),
    call: ({ entity_id }, env) => getEntity(entity_id, env),
  },
  {
    id: 'entities.neighborhood',
    description: 'Read up to 50 one-hop neighbors of one tenant entity.',
    api: 'GET /v1/entities/{entity_id}/neighborhood',
    owner: 'identity',
    cli: 'aether entities neighborhood',
    mcp: 'entities_neighborhood',
    input: z.object({
      entity_id: z.string().trim().min(1).max(256),
      limit: z.number().int().min(1).max(50).optional(),
    }).strict(),
    call: ({ entity_id, limit }, env) => getEntityNeighborhood(entity_id, { limit }, env),
  },
  {
    id: 'agent_access.observed.list',
    description: 'Read observed third-party agent access inventory; records are not executable grants.',
    api: 'GET /v1/capability-catalog',
    owner: 'agent_access_intelligence',
    cli: 'aether agents capabilities list',
    mcp: 'agent_access_capabilities_list',
    input: z.object({
      provider: z.string().max(128).optional(),
      server_name: z.string().max(128).optional(),
      tool_name: z.string().max(128).optional(),
      limit: z.number().int().min(1).max(100).optional(),
      offset: z.number().int().min(0).max(100_000).optional(),
    }).strict(),
    call: ({ provider, server_name, tool_name, limit, offset }, env) => listCapabilities({
      provider, serverName: server_name, toolName: tool_name, limit, offset,
    }, env),
  },
  {
    id: 'agent_access.observed.overview',
    description: 'Read a summary of observed third-party agent access.',
    api: 'GET /v1/capability-catalog/overview',
    owner: 'agent_access_intelligence',
    cli: 'aether agents capabilities overview',
    mcp: 'agent_access_capabilities_overview',
    input: z.object({}).strict(),
    call: (_input, env) => getCapabilityOverview(env),
  },
  {
    id: 'agent_access.observed.get',
    description: 'Read one observed third-party agent access record.',
    api: 'GET /v1/capability-catalog/{capability_id}',
    owner: 'agent_access_intelligence',
    cli: 'aether agents capabilities show',
    mcp: null,
    input: z.object({ capability_id: z.string().regex(/^cap_[a-f0-9]{24}$/) }).strict(),
    call: ({ capability_id }, env) => getCapability(capability_id, env),
  },
  {
    id: 'agents.behavior',
    description: 'Read the evidence-qualified Agent360 behavior read model for one source-reported agent ref; not an identity resolution.',
    api: 'GET /v1/agent/agents/{agent_ref}/behavior',
    owner: 'agent_behavior',
    required_server_permission: 'agent:manage',
    cli: 'aether agents behavior show',
    mcp: 'agents_behavior',
    input: z.object({ agent_ref: agentRef }).strict(),
    call: ({ agent_ref }, env) => getAgentBehavior(agent_ref, env),
  },
  {
    id: 'agents.decision',
    description: 'Read one reconstructed agent decision with attribution, responsibility roles, and a labelled counterfactual.',
    api: 'GET /v1/agent/agents/{agent_ref}/decisions/{decision_id}',
    owner: 'agent_behavior',
    required_server_permission: 'agent:manage',
    cli: 'aether agents decisions show',
    mcp: 'agents_decision',
    input: z.object({ agent_ref: agentRef, decision_id: z.string().trim().min(1).max(256) }).strict(),
    call: ({ agent_ref, decision_id }, env) => getAgentDecision(agent_ref, decision_id, env),
  },
  {
    id: 'usage.summary',
    description: 'Read the current non-billable Access Kit interaction count.',
    api: 'GET /v1/billing/usage/summary',
    owner: 'billing_usage',
    cli: 'aether usage summary',
    mcp: 'usage_summary',
    input: z.object({}).strict(),
    call: (_input, env) => getUsageSummary(env),
  },
];

const byId = new Map(definitions.map((definition) => [definition.id, definition]));
if (byId.size !== definitions.length) throw new Error('Duplicate Access Kit operation ID.');
for (const definition of definitions) {
  if (!SERVER_PERMISSIONS.includes(definition.required_server_permission ?? DEFAULT_SERVER_PERMISSION)) {
    throw new Error(`Unknown server permission for Access Kit operation ${definition.id}.`);
  }
}

function describe(definition) {
  return {
    id: definition.id,
    description: definition.description,
    operation: 'query',
    required_server_permission: definition.required_server_permission ?? DEFAULT_SERVER_PERMISSION,
    api: definition.api,
    owner: definition.owner,
    cli: definition.cli,
    mcp: definition.mcp,
    mcp_invoke: 'access_invoke_read',
    authorization: 'server_decides_per_request',
  };
}

export const accessOperationIds = Object.freeze(definitions.map(({ id }) => id));

export function listAccessOperations() {
  return definitions.map(describe);
}

export function getAccessOperation(id) {
  const definition = byId.get(id);
  return definition ? describe(definition) : null;
}

export async function invokeAccessOperation(id, input = {}, env = process.env) {
  const definition = byId.get(id);
  if (!definition) throw new Error('Unsupported Access Kit operation ID.');
  const parsed = definition.input.safeParse(input);
  if (!parsed.success) throw new Error(`Invalid input for Access Kit operation ${id}.`);
  return definition.call(parsed.data, env);
}
