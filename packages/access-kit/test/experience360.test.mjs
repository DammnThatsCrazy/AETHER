import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { registerAccessOperationTools } from '../src/access-operation-tools.mjs';
import {
  accessOperationIds,
  getAccessOperation,
  invokeAccessOperation,
  listAccessOperations,
} from '../src/access-operations.mjs';
import { AccessApiError, classifyHttpStatus } from '../src/api.mjs';
import { EXPERIENCE360_SURFACES } from '../src/experience360-catalog.mjs';
import { createAccessClient } from '../src/index.mjs';
import { frameFor } from './experience360-fixtures.mjs';

const OPERATION_ID = 'experience360.frame.get';
const env = { AETHER_API_KEY: 'frame-key-for-tests', AETHER_API_URL: 'https://api.example.test' };
const cliPath = fileURLToPath(new URL('../bin/aether.js', import.meta.url));
const preloadPath = fileURLToPath(new URL('./mock-fetch.mjs', import.meta.url));
const registryPath = fileURLToPath(
  new URL('../../shared/contracts/intelligence-projection-registry.json', import.meta.url),
);

const validInput = () => ({
  surface: 'agent360',
  subject: { kind: 'agent', id: 'agent-1' },
  requested_slots: ['identity', 'tool_usage', 'risk_summary', 'capabilities'],
  as_of: '2026-10-29T10:00:00Z',
  include_evidence: true,
});

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

const frameResponse = (call, headers = {}) => new Response(JSON.stringify(frameFor(call.body)), {
  status: 200,
  headers: { 'content-type': 'application/json', 'x-request-id': 'req-frame', ...headers },
});

function capturedMcpTools() {
  const tools = new Map();
  registerAccessOperationTools({
    registerTool(name, config, handler) { tools.set(name, { config, handler }); },
  }, env);
  return tools;
}

function runCli(args, extraEnv = {}) {
  return spawnSync(process.execPath, ['--import', preloadPath, cliPath, ...args], {
    encoding: 'utf8',
    env: {
      ...process.env,
      AETHER_API_KEY: 'cli-test-secret',
      AETHER_API_URL: 'https://api.example.test',
      ACCESS_KIT_MOCK_TRACE: '1',
      ...extraEnv,
    },
  });
}

const cliFrameArgs = [
  'experience360', 'frame', 'get', '--surface', 'agent360', '--subject-kind', 'agent',
  '--subject-id', 'agent-1', '--slots', 'identity,tool_usage,risk_summary,capabilities',
  '--as-of', '2026-10-29T10:00:00Z', '--json',
];

test('operation list declares the bounded 360 frame read once, as a read-only closed-table entry', () => {
  assert.equal(accessOperationIds.length, 9);
  assert.equal(accessOperationIds.filter((id) => id === OPERATION_ID).length, 1);
  const operation = getAccessOperation(OPERATION_ID);
  assert.deepEqual(
    { ...operation, description: undefined },
    {
      id: OPERATION_ID,
      description: undefined,
      operation: 'query',
      required_server_permission: 'read',
      api: 'POST /v1/experience360/frames',
      owner: 'experience360_projection',
      cli: 'aether experience360 frame get',
      mcp: null,
      mcp_invoke: 'access_invoke_read',
      authorization: 'server_decides_per_request',
    },
  );
  assert.deepEqual(listAccessOperations().map(({ id }) => id), [...accessOperationIds]);
});

test('operation discovery is identical across Node client, CLI, and MCP', async () => {
  const expected = listAccessOperations();
  const client = createAccessClient({ apiUrl: env.AETHER_API_URL, apiKey: env.AETHER_API_KEY });
  assert.deepEqual(client.operations.list(), expected);
  assert.deepEqual(client.operations.show(OPERATION_ID), getAccessOperation(OPERATION_ID));

  const cli = runCli(['access', 'operations', 'list', '--json']);
  assert.equal(cli.status, 0, cli.stderr);
  assert.deepEqual(JSON.parse(cli.stdout).operations, expected);
  const cliShow = runCli(['access', 'operations', 'show', OPERATION_ID, '--json']);
  assert.equal(cliShow.status, 0, cliShow.stderr);
  assert.deepEqual(JSON.parse(cliShow.stdout).operation, getAccessOperation(OPERATION_ID));

  const mcp = capturedMcpTools();
  const listed = await mcp.get('access_operations_list').handler({});
  assert.deepEqual(listed.structuredContent.operations, expected);
  assert.equal(mcp.get('access_operations_list').config.outputSchema.safeParse(
    listed.structuredContent,
  ).success, true);
  assert.equal(mcp.get('access_invoke_read').config.inputSchema.safeParse({
    operation_id: OPERATION_ID, input: validInput(),
  }).success, true);
  assert.equal(mcp.get('access_invoke_read').config.inputSchema.safeParse({
    operation_id: OPERATION_ID, input: validInput(), tenant_id: 'other',
  }).success, false);
});

test('pinned catalog allowlist matches the shared projection registry', () => {
  const registry = JSON.parse(readFileSync(registryPath, 'utf8'));
  const expected = Object.fromEntries(registry.productSurfaces.map((surface) => [surface.id, {
    subjectKinds: [...surface.subjectKinds],
    slots: surface.domainSlots.map((slot) => slot.id),
  }]));
  const actual = Object.fromEntries(Object.entries(EXPERIENCE360_SURFACES).map(([id, value]) => [id, {
    subjectKinds: [...value.subjectKinds],
    slots: [...value.slots],
  }]));
  assert.deepEqual(actual, expected);
});

test('invalid, oversized, unknown-field, and tenant-bearing input is rejected before any network call', async (t) => {
  const calls = installFetch(t, (call) => frameResponse(call));
  const slots = EXPERIENCE360_SURFACES.agent360.slots;
  const bad = {
    'unknown surface': { ...validInput(), surface: 'admin360' },
    'tenant id': { ...validInput(), tenant_id: 'tenant-other' },
    'camel tenant id': { ...validInput(), tenantId: 'tenant-other' },
    'tenant in subject': { ...validInput(), subject: { kind: 'agent', id: 'a', tenant_id: 'tenant-other' } },
    'graph query': { ...validInput(), query: 'MATCH (n) RETURN n' },
    'raw cypher': { ...validInput(), cypher: 'MATCH (n) RETURN n' },
    'authorization context override': { ...validInput(), authorization_context_ref: 'allow-all' },
    'policy override': { ...validInput(), policy: { disposition: 'allowed' } },
    'actor override': { ...validInput(), actor_id: 'someone-else' },
    'paging': { ...validInput(), page: { limit: 500 } },
    'limit': { ...validInput(), limit: 10_000 },
    'lens ids': { ...validInput(), lens_ids: ['a'] },
    'time range': { ...validInput(), time_range: { from: '2020-01-01T00:00:00Z' } },
    'provider url': { ...validInput(), provider_url: 'https://evil.example.test' },
    'missing surface': { subject: { kind: 'agent', id: 'a' } },
    'missing subject': { surface: 'agent360' },
    'subject kind not allowed for surface': { ...validInput(), subject: { kind: 'campaign', id: 'c1' } },
    'unknown subject kind': { ...validInput(), subject: { kind: 'tenant', id: 't1' } },
    'empty subject id': { ...validInput(), subject: { kind: 'agent', id: '' } },
    'oversized subject id': { ...validInput(), subject: { kind: 'agent', id: 'a'.repeat(257) } },
    'control character in subject id': { ...validInput(), subject: { kind: 'agent', id: 'a\nb' } },
    'padded subject id': { ...validInput(), subject: { kind: 'agent', id: ' a ' } },
    'empty slot list': { ...validInput(), requested_slots: [] },
    'unknown slot': { ...validInput(), requested_slots: ['not_a_slot'] },
    'slot from another surface': { ...validInput(), requested_slots: ['campaign_identity'] },
    'duplicate slots': { ...validInput(), requested_slots: ['identity', 'identity'] },
    'too many slots': { ...validInput(), requested_slots: [...slots, ...slots, ...slots] },
    'non-string slot': { ...validInput(), requested_slots: [1] },
    'as_of without timezone': { ...validInput(), as_of: '2026-10-29T10:00:00' },
    'as_of impossible date': { ...validInput(), as_of: '2026-02-31T00:00:00Z' },
    'as_of garbage': { ...validInput(), as_of: 'yesterday' },
    'as_of oversized': { ...validInput(), as_of: `2026-10-29T10:00:00.${'1'.repeat(80)}Z` },
    'include_evidence not boolean': { ...validInput(), include_evidence: 'yes' },
  };
  const client = createAccessClient({ apiUrl: env.AETHER_API_URL, apiKey: env.AETHER_API_KEY });
  for (const [label, input] of Object.entries(bad)) {
    await assert.rejects(() => invokeAccessOperation(OPERATION_ID, input, env), /Invalid input/, label);
    await assert.rejects(() => client.experience360.frame(input), /Invalid input/, label);
  }
  await assert.rejects(() => invokeAccessOperation(OPERATION_ID, null, env), /Invalid input/);
  assert.equal(calls.length, 0, 'no request may be made for rejected input');

  const tools = capturedMcpTools();
  for (const [label, input] of Object.entries(bad)) {
    const result = await tools.get('access_invoke_read').handler({ operation_id: OPERATION_ID, input });
    assert.equal(result.isError, true, label);
  }
  assert.equal(calls.length, 0);

  const cli = runCli([
    'experience360', 'frame', 'get', '--surface', 'agent360', '--subject-kind', 'campaign',
    '--subject-id', 'c1', '--json',
  ]);
  assert.equal(cli.status, 1);
  assert.doesNotMatch(cli.stderr, /MOCK_FETCH/);
  const cliExtra = runCli([...cliFrameArgs, '--tenant-id', 'tenant-other']);
  assert.equal(cliExtra.status, 1);
  assert.doesNotMatch(cliExtra.stderr, /MOCK_FETCH/);
});

test('the wire request is one POST to the mounted route with only allowlisted body fields and no tenant', async (t) => {
  const calls = installFetch(t, (call) => frameResponse(call));
  await invokeAccessOperation(OPERATION_ID, validInput(), env);
  assert.equal(calls.length, 1);
  const [call] = calls;
  assert.equal(call.url.pathname, '/v1/experience360/frames');
  assert.equal(call.url.search, '');
  assert.equal(call.init.method, 'POST');
  assert.equal(call.init.redirect, 'error');
  assert.deepEqual(call.body, {
    surfaceId: 'agent360',
    subject: { kind: 'agent', id: 'agent-1' },
    requestedSlotIds: ['identity', 'tool_usage', 'risk_summary', 'capabilities'],
    asOf: '2026-10-29T10:00:00Z',
    includeEvidence: true,
  });
  const headerNames = Object.keys(call.init.headers).map((name) => name.toLowerCase());
  assert.deepEqual(
    headerNames.filter((name) => name.includes('tenant') || name.includes('actor')),
    [],
  );
  assert.equal(JSON.stringify(call).includes('tenant'), false);

  await invokeAccessOperation(OPERATION_ID, {
    surface: 'profile360', subject: { kind: 'profile', id: 'p-1' },
  }, env);
  assert.deepEqual(calls[1].body, { surfaceId: 'profile360', subject: { kind: 'profile', id: 'p-1' } });
});

test('Node client, MCP, and CLI return the same unmodified server frame with partial and unknown preserved', async (t) => {
  const calls = installFetch(t, (call) => frameResponse(call, {
    'x-aether-audit-event-id': 'audit-from-server',
  }));
  const expectedFrame = frameFor({ surfaceId: 'agent360', subject: validInput().subject });

  const client = createAccessClient({ apiUrl: env.AETHER_API_URL, apiKey: env.AETHER_API_KEY });
  const viaClient = await client.experience360.frame(validInput());
  assert.deepEqual(viaClient.data, expectedFrame);
  assert.equal(viaClient.request_id, 'req-frame');
  assert.equal(viaClient.interaction.status_class, 'successful');
  assert.equal(calls.at(-1).init.headers['x-aether-access-surface'], 'access_sdk');

  const tools = capturedMcpTools();
  const viaMcp = await tools.get('access_invoke_read').handler({
    operation_id: OPERATION_ID, input: validInput(),
  });
  assert.equal(viaMcp.isError, undefined);
  assert.deepEqual(viaMcp.structuredContent.data, expectedFrame);
  assert.equal(tools.get('access_invoke_read').config.outputSchema.safeParse(
    viaMcp.structuredContent,
  ).success, true);

  const cli = runCli(cliFrameArgs);
  assert.equal(cli.status, 0, cli.stderr);
  const viaCli = JSON.parse(cli.stdout);
  assert.deepEqual(viaCli.data, expectedFrame);
  assert.match(cli.stderr, /MOCK_FETCH POST \/v1\/experience360\/frames redirect=error surface=cli/);
  assert.equal(`${cli.stdout}${cli.stderr}`.includes('cli-test-secret'), false);

  for (const data of [viaClient.data, viaMcp.structuredContent.data, viaCli.data]) {
    const byId = Object.fromEntries(data.slots.map((slot) => [slot.id, slot]));
    assert.equal(data.state, 'partial');
    assert.equal(byId.tool_usage.state, 'unknown');
    assert.equal(byId.tool_usage.content, undefined);
    assert.equal(byId.risk_summary.state, 'degraded');
    assert.deepEqual(byId.risk_summary.limitations, ['source_stale']);
    assert.equal(byId.capabilities.state, 'suppressed');
    assert.equal(byId.capabilities.policyDisposition.state, 'denied');
    assert.deepEqual(byId.identity.evidenceRefs, ['ev-1']);
    assert.deepEqual(data.degradation, { degraded: true, reasonCodes: ['freshness_exceeded'] });
    assert.equal(data.ownsCanonicalTruth, false);
  }
});

test('receipt references come only from server headers; none are fabricated', async (t) => {
  let withHeaders = false;
  installFetch(t, (call) => frameResponse(call, withHeaders ? {
    'x-aether-audit-event-id': 'audit-from-server',
    'x-aether-usage-event-id': 'usage-from-server',
  } : {}));
  const plain = await invokeAccessOperation(OPERATION_ID, validInput(), env);
  assert.deepEqual(plain.interaction.references, {});
  assert.equal(plain.responseRequestId, undefined);

  withHeaders = true;
  const receipted = await invokeAccessOperation(OPERATION_ID, validInput(), env);
  assert.deepEqual(receipted.interaction.references, {
    usage_event_id: 'usage-from-server',
    audit_event_id: 'audit-from-server',
  });
});

test('HTTP 401/403/404/409/422/429/5xx become typed, non-sensitive errors with one attempt', async (t) => {
  const expected = [
    [401, 'unauthenticated', 'denied'],
    [403, 'forbidden', 'denied'],
    [404, 'not_found', 'failed'],
    [409, 'conflict', 'failed'],
    [422, 'invalid_request', 'failed'],
    [429, 'rate_limited', 'blocked'],
    [500, 'server_error', 'failed'],
    [503, 'server_error', 'failed'],
  ];
  let status = 0;
  const calls = installFetch(t, () => new Response(JSON.stringify({
    detail: 'SECRET-DETAIL tenant-private', error: { code: 'server_code' },
  }), {
    status,
    headers: {
      'content-type': 'application/json',
      'x-request-id': 'req-error',
      ...(status === 429 ? { 'retry-after': '30' } : {}),
    },
  }));
  const tools = capturedMcpTools();
  for (const [httpStatus, category, statusClass] of expected) {
    status = httpStatus;
    const before = calls.length;
    const error = await invokeAccessOperation(OPERATION_ID, validInput(), env).then(
      () => assert.fail(`expected HTTP ${httpStatus} to throw`),
      (thrown) => thrown,
    );
    assert.ok(error instanceof AccessApiError);
    assert.equal(error.status, httpStatus);
    assert.equal(error.category, category);
    assert.equal(error.code, 'server_code');
    assert.equal(error.interaction.status_class, statusClass);
    assert.equal(error.requestId, 'req-error');
    assert.equal(error.retryAfterSeconds, httpStatus === 429 ? 30 : undefined);
    assert.equal(JSON.stringify([error.message, error.interaction]).includes('SECRET'), false);
    assert.equal(calls.length - before, 1, `HTTP ${httpStatus} must not be retried`);

    const result = await tools.get('access_invoke_read').handler({
      operation_id: OPERATION_ID, input: validInput(),
    });
    assert.equal(result.isError, true);
    const details = JSON.parse(result.content[0].text).error;
    assert.equal(details.status, httpStatus);
    assert.equal(details.category, category);
    assert.equal(JSON.stringify(details).includes('SECRET'), false);
    if (httpStatus === 429) assert.equal(details.retry_after_seconds, 30);
  }
  assert.equal(classifyHttpStatus(200), undefined);
});

test('CLI preserves the HTTP error taxonomy as non-sensitive typed JSON', () => {
  for (const [status, category] of [[401, 'unauthenticated'], [403, 'forbidden'], [404, 'not_found'], [429, 'rate_limited']]) {
    const result = runCli(cliFrameArgs, { ACCESS_KIT_MOCK_FRAME_STATUS: String(status) });
    assert.equal(result.status, 1);
    const details = JSON.parse(result.stderr.split('\n').filter((line) => line.startsWith('{')).at(-1)).error;
    assert.equal(details.status, status);
    assert.equal(details.category, category);
    assert.equal(details.request_id, 'cli-frame-error-id');
    if (status === 429) assert.equal(details.retry_after_seconds, 7);
    assert.equal(result.stderr.includes('SECRET-DETAIL'), false);
    assert.equal(result.stdout, '');
  }
});

test('a frame for a different surface or subject, or a non-frame body, is a contract error and not data', async (t) => {
  let body;
  installFetch(t, () => new Response(JSON.stringify(body), {
    status: 200, headers: { 'content-type': 'application/json', 'x-request-id': 'req-contract' },
  }));
  const good = frameFor({ surfaceId: 'agent360', subject: { kind: 'agent', id: 'agent-1' } });
  const cases = {
    'wrong surface': { ...good, surfaceId: 'profile360' },
    'wrong subject id': { ...good, subject: { kind: 'agent', id: 'someone-else' } },
    'wrong subject kind': { ...good, subject: { kind: 'entity', id: 'agent-1' } },
    'missing slots': { ...good, slots: undefined },
    'too many slots': { ...good, slots: Array.from({ length: 65 }, (_, index) => ({ id: `s${index}`, state: 'unknown' })) },
    'oversized frame': { ...good, extra: 'x'.repeat(4 * 1024 * 1024 + 1) },
    'array body': [good],
  };
  for (const [label, value] of Object.entries(cases)) {
    body = value;
    const error = await invokeAccessOperation(OPERATION_ID, validInput(), env).then(
      () => assert.fail(label), (thrown) => thrown,
    );
    assert.ok(error instanceof AccessApiError, label);
    assert.equal(error.interaction.status_class, 'failed', label);
  }
});

test('a transport failure is surfaced once without retry', async (t) => {
  const calls = installFetch(t, () => { throw new TypeError('connection refused to secret-host'); });
  const error = await invokeAccessOperation(OPERATION_ID, validInput(), env).then(
    () => assert.fail('expected failure'), (thrown) => thrown,
  );
  assert.ok(error instanceof AccessApiError);
  assert.equal(error.message.includes('secret-host'), false);
  assert.equal(calls.length, 1);
});
