import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { getAccessOperation, invokeAccessOperation } from '../src/access-operations.mjs';
import { EXPERIENCE360_SURFACES } from '../src/experience360-catalog.mjs';
import { PROFILE360_TOOL_NAMES, registerProfile360Tools } from '../src/profile360-tools.mjs';
import { createAccessMcpServer } from '../bin/aether-mcp.js';
import { frameFor } from './experience360-fixtures.mjs';

const env = { AETHER_API_KEY: 'p360-key-for-tests', AETHER_API_URL: 'https://api.example.test' };
const cliPath = fileURLToPath(new URL('../bin/aether.js', import.meta.url));
const preloadPath = fileURLToPath(new URL('./mock-fetch.mjs', import.meta.url));

function installFetch(t, handler) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const call = { url: new URL(url), init, body: init?.body ? JSON.parse(init.body) : undefined };
    calls.push(call);
    return handler(call);
  };
  t.after(() => { globalThis.fetch = original; });
  return calls;
}

const frameResponse = (call) => new Response(JSON.stringify(frameFor(call.body)), {
  status: 200, headers: { 'content-type': 'application/json', 'x-request-id': 'req-p360' },
});

function runCli(args) {
  return spawnSync(process.execPath, ['--import', preloadPath, cliPath, ...args], {
    encoding: 'utf8',
    env: { ...process.env, ...env, ACCESS_KIT_MOCK_TRACE: '1' },
  });
}

function capturedTools() {
  const tools = new Map();
  registerProfile360Tools({ registerTool(name, config, handler) { tools.set(name, { config, handler }); } }, env);
  return tools;
}

test('four named Profile360 reads are declared read-only with named MCP tools and CLI commands', () => {
  const expected = {
    'profile360.get': ['POST /v1/experience360/frames', 'profile360_get', 'aether profile360 get'],
    'profile360.slot.get': ['POST /v1/experience360/frames', 'profile360_slot_get', 'aether profile360 slots'],
    'profile360.evidence.get': ['POST /v1/experience360/frames', 'profile360_evidence_get', 'aether profile360 evidence'],
    'profile360.search': ['POST /v1/profile/resolve', 'profile360_search', 'aether profile360 search'],
  };
  for (const [id, [api, mcp, cli]] of Object.entries(expected)) {
    const op = getAccessOperation(id);
    assert.equal(op.required_server_permission, 'read', id);
    assert.equal(op.api, api, id);
    assert.equal(op.mcp, mcp, id);
    assert.equal(op.cli, cli, id);
  }
  assert.deepEqual([...PROFILE360_TOOL_NAMES].sort(), Object.values(expected).map((v) => v[1]).sort());
});

test('profile360.get sends one bounded frame request for an entity with evidence on by default', async (t) => {
  const calls = installFetch(t, frameResponse);
  const result = await invokeAccessOperation('profile360.get', { entity_id: 'ent-1' }, env);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, '/v1/experience360/frames');
  assert.deepEqual(calls[0].body, {
    surfaceId: 'profile360', subject: { kind: 'entity', id: 'ent-1' }, includeEvidence: true,
  });
  assert.deepEqual(result.data, frameFor(calls[0].body));
});

test('profile360.slot.get requests only the named slots', async (t) => {
  const calls = installFetch(t, frameResponse);
  await invokeAccessOperation('profile360.slot.get', {
    entity_id: 'ent-1', slots: ['risk_summary', 'value_summary'],
  }, env);
  assert.deepEqual(calls[0].body.requestedSlotIds, ['risk_summary', 'value_summary']);
});

test('profile360.evidence.get returns evidence, provenance and reasons verbatim and omits content', async (t) => {
  const calls = installFetch(t, frameResponse);
  const result = await invokeAccessOperation('profile360.evidence.get', { entity_id: 'ent-1' }, env);
  const frame = frameFor(calls[0].body);
  assert.equal(result.data.view, 'profile360_evidence');
  assert.equal(result.data.slots.length, frame.slots.length);
  for (const [index, slot] of result.data.slots.entries()) {
    const source = frame.slots[index];
    assert.equal(slot.id, source.id);
    assert.equal(slot.state, source.state);
    assert.deepEqual(slot.evidenceRefs, source.evidenceRefs ?? []);
    assert.deepEqual(slot.reasonCodes, source.reasonCodes ?? []);
    assert.equal('content' in slot, false);
  }
});

test('profile360.search sends the identifier in the body, never the URL', async (t) => {
  const calls = installFetch(t, () => new Response(JSON.stringify({ data: { resolved_user_id: 'ent-9' } }), {
    status: 200, headers: { 'content-type': 'application/json', 'x-request-id': 'req-resolve' },
  }));
  const result = await invokeAccessOperation('profile360.search', { email: 'person@example.com' }, env);
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].url.pathname, '/v1/profile/resolve');
  assert.equal(calls[0].url.search, '');
  assert.deepEqual(calls[0].body, { email: 'person@example.com' });
  assert.deepEqual(result.data, { entity_id: 'ent-9', subject: { kind: 'entity', id: 'ent-9' } });
});

test('a malformed resolution response is a contract error, not data', async (t) => {
  installFetch(t, () => new Response(JSON.stringify({ data: { something: 'else' } }), {
    status: 200, headers: { 'content-type': 'application/json' },
  }));
  await assert.rejects(invokeAccessOperation('profile360.search', { customer: 'c-1' }, env));
});

test('invalid input is rejected before any network call', async (t) => {
  const calls = installFetch(t, frameResponse);
  const slots = EXPERIENCE360_SURFACES.profile360.slots;
  const bad = [
    ['profile360.get', {}],
    ['profile360.get', { entity_id: 'e', tenant_id: 'other' }],
    ['profile360.get', { entity_id: 'e', subject_kind: 'campaign' }],
    ['profile360.slot.get', { entity_id: 'e' }],
    ['profile360.slot.get', { entity_id: 'e', slots: ['not_a_slot'] }],
    ['profile360.slot.get', { entity_id: 'e', slots: ['risk_summary', 'risk_summary'] }],
    ['profile360.slot.get', { entity_id: 'e', slots: slots.slice(0, 9) }],
    ['profile360.search', {}],
    ['profile360.search', { email: 'a@b.c', wallet: '0x1' }],
    ['profile360.search', { phone: '555' }],
  ];
  for (const [id, input] of bad) {
    await assert.rejects(invokeAccessOperation(id, input, env), `${id} ${JSON.stringify(input)}`);
  }
  assert.equal(calls.length, 0);
});

test('named MCP tools return the same server data as the operation table', async (t) => {
  const calls = installFetch(t, frameResponse);
  const tools = capturedTools();
  const viaTool = await tools.get('profile360_get').handler({ entity_id: 'ent-1' });
  assert.equal(viaTool.isError, undefined);
  assert.equal(tools.get('profile360_get').config.outputSchema.safeParse(viaTool.structuredContent).success, true);
  assert.deepEqual(viaTool.structuredContent.data, frameFor(calls[0].body));
  assert.equal(tools.get('profile360_get').config.annotations.readOnlyHint, true);
  const invalid = await tools.get('profile360_slot_get').handler({ entity_id: 'e', slots: [] });
  assert.equal(invalid.isError, true);
});

test('delegated OAuth MCP sessions still advertise the read-only Profile360 tools', () => {
  const names = (server) => Object.keys(server._registeredTools ?? {});
  const oauth = createAccessMcpServer({ ...env, AETHER_API_KEY: undefined, AETHER_MCP_OAUTH_TOKEN: 'token' });
  for (const name of PROFILE360_TOOL_NAMES) assert.ok(names(oauth).includes(name), name);
});

test('CLI profile360 commands use the same operations and keep identifiers out of the URL', () => {
  const get = runCli(['profile360', 'get', 'ent-1', '--json']);
  assert.equal(get.status, 0, get.stderr);
  assert.equal(JSON.parse(get.stdout).operation_id, 'profile360.get');
  assert.match(get.stderr, /MOCK_FETCH POST \/v1\/experience360\/frames redirect=error surface=cli/);

  const slots = runCli(['profile360', 'slots', 'ent-1', '--slots', 'risk_summary,value_summary', '--json']);
  assert.equal(slots.status, 0, slots.stderr);
  assert.match(slots.stderr, /"requestedSlotIds":\["risk_summary","value_summary"\]/);

  const evidence = runCli(['profile360', 'evidence', 'ent-1', '--json']);
  assert.equal(evidence.status, 0, evidence.stderr);
  assert.equal(JSON.parse(evidence.stdout).data.view, 'profile360_evidence');

  const search = runCli(['profile360', 'search', '--email', 'person@example.com', '--json']);
  assert.equal(search.status, 0, search.stderr);
  assert.equal(JSON.parse(search.stdout).data.entity_id, 'ent-resolved');
  assert.match(search.stderr, /MOCK_FETCH POST \/v1\/profile\/resolve redirect=error/);
  assert.doesNotMatch(search.stderr, /MOCK_FETCH [^\n]*person@example\.com/);

  const bad = runCli(['profile360', 'slots', 'ent-1', '--json']);
  assert.equal(bad.status, 1);
  assert.doesNotMatch(bad.stderr, /MOCK_FETCH/);
});

test('Node client exposes the same Profile360 reads', async (t) => {
  const { createAccessClient } = await import('../src/index.mjs');
  const calls = installFetch(t, (call) => (call.url.pathname === '/v1/profile/resolve'
    ? new Response(JSON.stringify({ data: { resolved_user_id: 'ent-2' } }), {
      status: 200, headers: { 'content-type': 'application/json' },
    })
    : frameResponse(call)));
  const client = createAccessClient({ apiUrl: env.AETHER_API_URL, apiKey: env.AETHER_API_KEY });
  const found = await client.profile360.search({ wallet: '0xabc' });
  assert.equal(found.data.entity_id, 'ent-2');
  await client.profile360.get('ent-2');
  await client.profile360.slots('ent-2', ['risk_summary']);
  const evidence = await client.profile360.evidence('ent-2');
  assert.equal(evidence.data.view, 'profile360_evidence');
  assert.equal(calls.length, 4);
  assert.ok(calls.every((call) => call.init.headers['x-aether-access-surface'] === 'access_sdk'));
});
