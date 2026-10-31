import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { AccessApiError, getAgentBehavior, getAgentDecision } from '../src/api.mjs';
import {
  accessOperationIds,
  getAccessOperation,
  invokeAccessOperation,
  listAccessOperations,
} from '../src/access-operations.mjs';
import { registerAgentBehaviorTools } from '../src/agent-behavior-tools.mjs';
import { registerAccessOperationTools } from '../src/access-operation-tools.mjs';

const readEnv = {
  AETHER_API_KEY: 'read-key-for-tests',
  AETHER_API_URL: 'https://api.example.test',
};

function jsonResponse(payload, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

function captureFetch(t, payload, options) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    return jsonResponse(payload, options);
  };
  return calls;
}

const behavior = {
  agent_ref: 'agent/1', read_model_version: '1', model: {}, source_truncated: true,
  sections: { behavior: { state: 'partial', data: { evidence: ['evt-1'] } } },
};

test('operation table keeps read as the default and declares agent:manage only for behavior reads', () => {
  assert.deepEqual(accessOperationIds, [
    'account.context', 'entities.list', 'entities.get', 'entities.neighborhood',
    'agent_access.observed.list', 'agent_access.observed.overview', 'agent_access.observed.get',
    'agents.behavior', 'agents.decision', 'usage.summary',
  ]);
  const permissions = Object.fromEntries(listAccessOperations()
    .map(({ id, required_server_permission }) => [id, required_server_permission]));
  for (const id of accessOperationIds) {
    assert.equal(permissions[id], id.startsWith('agents.') ? 'agent:manage' : 'read', id);
  }
  assert.deepEqual(getAccessOperation('agents.behavior'), {
    id: 'agents.behavior',
    description: getAccessOperation('agents.behavior').description,
    operation: 'query',
    required_server_permission: 'agent:manage',
    api: 'GET /v1/agent/agents/{agent_ref}/behavior',
    owner: 'agent_behavior',
    cli: 'aether agents behavior show',
    mcp: 'agents_behavior',
    mcp_invoke: 'access_invoke_read',
    authorization: 'server_decides_per_request',
  });
  const decision = getAccessOperation('agents.decision');
  assert.equal(decision.api, 'GET /v1/agent/agents/{agent_ref}/decisions/{decision_id}');
  assert.equal(decision.owner, 'agent_behavior');
  assert.equal(decision.mcp, 'agents_decision');
});

test('access_operations_list output schema accepts the agent:manage descriptors', async () => {
  const tools = new Map();
  registerAccessOperationTools({ registerTool: (name, config, handler) => tools.set(name, { config, handler }) },
    readEnv);
  const tool = tools.get('access_operations_list');
  const result = await tool.handler({});
  assert.equal(tool.config.outputSchema.safeParse(result.structuredContent).success, true);
  assert.equal(tool.config.outputSchema.safeParse({
    catalog_kind: 'adapter_supported_operations',
    operations: [{ ...getAccessOperation('agents.behavior'), required_server_permission: 'admin' }],
  }).success, false);
});

test('behavior inputs are strict and bounded before any request', async (t) => {
  const calls = captureFetch(t, { data: behavior });
  await assert.rejects(invokeAccessOperation('agents.behavior', {}, readEnv), /Invalid input/);
  await assert.rejects(invokeAccessOperation('agents.behavior', { agent_ref: 'x'.repeat(257) }, readEnv),
    /Invalid input/);
  await assert.rejects(invokeAccessOperation('agents.behavior', {
    agent_ref: 'agent-1', tenant_id: 'tenant-override',
  }, readEnv), /Invalid input/);
  await assert.rejects(invokeAccessOperation('agents.decision', { agent_ref: 'agent-1' }, readEnv),
    /Invalid input/);
  await assert.rejects(getAgentDecision('agent-1', ' ', readEnv), /Decision IDs must contain/);
  assert.equal(calls.length, 0);
});

test('getAgentBehavior encodes the agent ref and passes the evidence-qualified model through', async (t) => {
  const calls = captureFetch(t, { data: behavior, meta: { request_id: 'api-id' } },
    { headers: { 'x-request-id': 'req-id' } });
  const result = await invokeAccessOperation('agents.behavior', { agent_ref: 'agent/1' }, readEnv);
  assert.equal(calls[0].url.pathname, '/v1/agent/agents/agent%2F1/behavior');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.redirect, 'error');
  assert.deepEqual(result.data, behavior);
  assert.equal(result.requestId, 'req-id');
  assert.equal(result.responseRequestId, 'api-id');
  assert.equal(result.interaction.operation, 'query');
  assert.equal(result.interaction.status_class, 'successful');
});

test('getAgentBehavior accepts the explicit unavailable shape and rejects a mismatched agent', async (t) => {
  captureFetch(t, { data: { agent_ref: 'agent-1', source_status: 'unavailable', sections: null } });
  const unavailable = await getAgentBehavior('agent-1', readEnv);
  assert.equal(unavailable.data.source_status, 'unavailable');
  await assert.rejects(getAgentBehavior('agent-2', readEnv), (error) => (
    error instanceof AccessApiError && /unexpected agent behavior/.test(error.message)
    && error.interaction.status_class === 'failed'
  ));
});

test('getAgentDecision rejects a decision owned by another agent', async (t) => {
  const calls = captureFetch(t, { data: {
    envelope: { decision_id: 'dec-1', decision_actor: { value: 'agent-other' } },
  } });
  await assert.rejects(getAgentDecision('agent-1', 'dec-1', readEnv), /unexpected agent decision/);
  assert.equal(calls[0].url.pathname, '/v1/agent/agents/agent-1/decisions/dec-1');
});

test('permission denials keep API status, code, and the denied interaction outcome', async (t) => {
  captureFetch(t, { error: { code: 'permission_denied' } }, { status: 403 });
  await assert.rejects(getAgentBehavior('agent-1', readEnv), (error) => (
    error instanceof AccessApiError && error.status === 403 && error.code === 'permission_denied'
    && error.interaction.status_class === 'denied'
  ));
});

test('MCP behavior tools are read-only, strict, and return request IDs', async () => {
  const tools = new Map();
  const interaction = { version: '1', operation: 'query', status_class: 'successful', request_id: 'r',
    http_status: 200, references: {} };
  registerAgentBehaviorTools({ registerTool: (name, config, handler) => tools.set(name, { config, handler }) }, {
    behavior: async () => ({ data: behavior, requestId: 'r', interaction }),
    decision: async () => ({ data: { envelope: { decision_id: 'd' } }, requestId: 'r', interaction }),
  });
  for (const name of ['agents_behavior', 'agents_decision']) {
    const tool = tools.get(name);
    assert.equal(tool.config.annotations.readOnlyHint, true);
    assert.equal(tool.config.inputSchema.safeParse({ agent_ref: 'a', decision_id: 'd', tenant_id: 't' })
      .success, false);
  }
  const result = await tools.get('agents_behavior').handler({ agent_ref: 'agent/1' });
  assert.deepEqual(result.structuredContent.behavior, behavior);
  assert.equal(tools.get('agents_behavior').config.outputSchema.safeParse(result.structuredContent).success, true);
  const decided = await tools.get('agents_decision').handler({ agent_ref: 'a', decision_id: 'd' });
  assert.equal(decided.structuredContent.decision.envelope.decision_id, 'd');
});

const cliPath = fileURLToPath(new URL('../bin/aether.js', import.meta.url));
const preloadPath = fileURLToPath(new URL('./mock-fetch.mjs', import.meta.url));

function runCli(args) {
  return spawnSync(process.execPath, ['--import', preloadPath, cliPath, ...args], {
    encoding: 'utf8',
    env: {
      ...process.env,
      AETHER_API_KEY: 'cli-test-secret',
      AETHER_API_URL: 'https://api.example.test',
      ACCESS_KIT_MOCK_TRACE: '1',
    },
  });
}

test('CLI agents behavior and decisions show call the owning routes', () => {
  const shown = runCli(['agents', 'behavior', 'show', 'agent-cli', '--json']);
  assert.equal(shown.status, 0, shown.stderr);
  const output = JSON.parse(shown.stdout);
  assert.equal(output.agent_ref, 'agent-cli');
  assert.equal(output.request_id, 'cli-request-id');
  assert.match(shown.stderr, /MOCK_FETCH GET \/v1\/agent\/agents\/agent-cli\/behavior redirect=error/);

  const decision = runCli(['agents', 'decisions', 'show', 'agent-cli', 'dec-cli', '--json']);
  assert.equal(decision.status, 0, decision.stderr);
  assert.equal(JSON.parse(decision.stdout).envelope.decision_id, 'dec-cli');

  const extra = runCli(['agents', 'behavior', 'show', 'agent-cli', 'extra', '--json']);
  assert.equal(extra.status, 1);
  assert.doesNotMatch(extra.stderr, /MOCK_FETCH/);
});
