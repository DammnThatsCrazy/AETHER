import assert from 'node:assert/strict';
import { once } from 'node:events';
import http from 'node:http';
import test from 'node:test';

import {
  CLIENT_CAPABILITIES_META_KEY,
  PROTOCOL_VERSION_META_KEY,
} from '@modelcontextprotocol/server';

import { createAccessKitHttpServer } from '../bin/aether-mcp-http.js';
import {
  DEFAULT_REMOTE_MCP_PATH,
  MCP_LIVENESS_PATH,
  MCP_READINESS_PATH,
  createRemoteMcpFetchHandler,
} from '../src/mcp-http.mjs';

const API_KEY = 'ak_0123456789abcdef01234567';
const SESSION_TOKEN = `sess_${'a'.repeat(48)}`;
const PUBLISHABLE_KEY = 'pk_0123456789abcdef01234567';
const ORIGIN = 'https://console.example.test';
const env = {
  AETHER_API_URL: 'https://api.example.test',
  AETHER_MCP_ALLOWED_HOSTS: 'mcp.example.test',
  AETHER_MCP_ALLOWED_ORIGINS: ORIGIN,
};

function apiResponse(data, { requestId = 'api-request', status = 200 } = {}) {
  return new Response(JSON.stringify({ data, meta: { request_id: requestId } }), {
    status,
    headers: { 'content-type': 'application/json', 'x-request-id': requestId },
  });
}

function mcpBody(method, params = {}, id = 1) {
  return {
    jsonrpc: '2.0',
    id,
    method,
    params: {
      ...params,
      _meta: {
        [PROTOCOL_VERSION_META_KEY]: '2026-07-28',
        [CLIENT_CAPABILITIES_META_KEY]: {},
      },
    },
  };
}

function mcpRequest(body, { token = API_KEY, host = 'mcp.example.test', headers = {} } = {}) {
  const requestHeaders = new Headers({
    host,
    accept: 'application/json',
    'content-type': 'application/json',
    authorization: `Bearer ${token}`,
    'mcp-protocol-version': '2026-07-28',
    'mcp-method': body.method,
    ...headers,
  });
  if (body.method === 'tools/call') requestHeaders.set('mcp-name', body.params.name);
  return new Request(`https://mcp.example.test${DEFAULT_REMOTE_MCP_PATH}`, {
    method: 'POST',
    headers: requestHeaders,
    body: JSON.stringify(body),
  });
}

function installApiFetch(t, { onRequest } = {}) {
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    const parsed = new URL(url);
    const record = { url: parsed, init };
    requests.push(record);
    onRequest?.(record);
    assert.equal(init.redirect, 'error');
    if (parsed.pathname === '/v1/me') {
      return apiResponse({
        tenant_id: 'must-not-be-forwarded',
        name: 'Example tenant',
        plan: { plan_id: 'team', display_name: 'Team', monthly_quota: 500, burst_rpm: 30 },
        billing: { subscription_status: 'active', current_period_end: null },
        api_key_count: 1,
        is_admin: false,
      }, { requestId: 'middleware-me' });
    }
    if (parsed.pathname === '/v1/entities') {
      return apiResponse({ entities: [], count: 0 }, { requestId: 'middleware-entities' });
    }
    if (parsed.pathname === '/v1/billing/usage/summary') {
      return apiResponse({
        usage_by_dimension: { access_interaction: 3, profile_query: 99 },
        billing_period_start: '2026-10-01T00:00:00Z',
        billing_period_end: '2026-11-01T00:00:00Z',
        status: 'available',
      }, { requestId: 'middleware-usage' });
    }
    if (parsed.pathname === '/v1/batch') {
      return new Response(JSON.stringify({
        accepted: 1,
        duplicates: 0,
        rejected: 0,
        events: [{ id: 'evt-remote-1', status: 'accepted' }],
        batchId: 'batch-remote-1',
        receivedAt: '2026-10-11T00:00:00Z',
        usageEventId: 'usage-1',
        usageEvidenceId: 'evidence-1',
        meta: { request_id: 'api-batch' },
      }), {
        headers: { 'content-type': 'application/json', 'x-request-id': 'middleware-batch' },
      });
    }
    assert.fail(`unexpected Aether API path ${parsed.pathname}`);
  };
  t.after(() => { globalThis.fetch = previousFetch; });
  return requests;
}

test('remote health and readiness are usable without a caller credential', async () => {
  const handler = createRemoteMcpFetchHandler({ env: {} });
  const health = await handler(new Request(`http://mcp.example.test${MCP_LIVENESS_PATH}`));
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: 'ok' });

  const notReady = await handler(new Request(`http://mcp.example.test${MCP_READINESS_PATH}`));
  assert.equal(notReady.status, 503);
  assert.deepEqual(await notReady.json(), { error: { code: 'configuration_not_ready' } });

  const ready = await createRemoteMcpFetchHandler({ env })(
    new Request(`http://mcp.example.test${MCP_READINESS_PATH}`),
  );
  assert.equal(ready.status, 200);
  assert.deepEqual(await ready.json(), { status: 'ready', path: DEFAULT_REMOTE_MCP_PATH });
});

test('remote MCP requires supported Aether bearer credentials and exact host/origin', async (t) => {
  const requests = installApiFetch(t);
  const handler = createRemoteMcpFetchHandler({ env });

  const missing = await handler(new Request(`https://mcp.example.test${DEFAULT_REMOTE_MCP_PATH}`, {
    method: 'POST',
    headers: { host: 'mcp.example.test', 'content-type': 'application/json' },
    body: JSON.stringify(mcpBody('tools/list')),
  }));
  assert.equal(missing.status, 401);
  assert.equal(missing.headers.get('www-authenticate'), null);

  const badBearer = await handler(mcpRequest(mcpBody('tools/list'), { token: 'pk_publishable' }));
  assert.equal(badBearer.status, 401);

  const badHost = await handler(mcpRequest(mcpBody('tools/list'), { host: 'attacker.example.test' }));
  assert.equal(badHost.status, 403);

  const badOrigin = await handler(mcpRequest(mcpBody('tools/list'), {
    headers: { origin: 'https://console.example.test:444' },
  }));
  assert.equal(badOrigin.status, 403);
  assert.equal(requests.length, 0);
});

test('remote list validates caller session on every request and omits observe without site credentials', async (t) => {
  const requests = installApiFetch(t);
  const handler = createRemoteMcpFetchHandler({ env });
  const response = await handler(mcpRequest(mcpBody('tools/list'), { token: SESSION_TOKEN }));
  assert.equal(response.status, 200);
  const result = await response.json();
  const tools = result.result.tools.map((tool) => tool.name);
  assert.ok(tools.includes('entities_list'));
  assert.ok(tools.includes('entities_get'));
  assert.ok(tools.includes('account_context'));
  assert.ok(tools.includes('usage_summary'));
  assert.ok(tools.includes('agents_behavior'));
  assert.ok(tools.includes('agents_decision'));
  assert.ok(tools.includes('agent_access_capabilities_list'));
  assert.ok(!tools.includes('observe'));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url.pathname, '/v1/me');
  assert.equal(requests[0].init.headers['x-session-token'], SESSION_TOKEN);
  assert.equal('authorization' in requests[0].init.headers, false);
  assert.equal(JSON.stringify(result).includes('must-not-be-forwarded'), false);
});

test('remote usage_summary calls the shared tenant API with MCP HTTP attribution', async (t) => {
  const requests = installApiFetch(t);
  const handler = createRemoteMcpFetchHandler({ env });
  const response = await handler(mcpRequest(mcpBody('tools/call', {
    name: 'usage_summary', arguments: {},
  })));
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.error, undefined, JSON.stringify(body));
  assert.equal(body.result.structuredContent.usage.access_interaction_count, 3);
  assert.equal(body.result.structuredContent.interaction.status_class, 'successful');
  const summaryCall = requests.find((request) => request.url.pathname === '/v1/billing/usage/summary');
  assert.ok(summaryCall);
  assert.equal(summaryCall.init.headers['x-aether-access-surface'], 'mcp_http');
  const preflight = requests.find((request) => request.url.pathname === '/v1/me');
  assert.equal(preflight.init.headers['x-aether-access-surface'], undefined);
  assert.doesNotMatch(JSON.stringify(body), /profile_query|usage_by_dimension/);
});

test('remote observe appears only with request-scoped publishable key and site, used only for batch', async (t) => {
  const requests = installApiFetch(t);
  const handler = createRemoteMcpFetchHandler({ env });
  const listResponse = await handler(mcpRequest(mcpBody('tools/list'), {
    headers: {
      'x-aether-observe-key': PUBLISHABLE_KEY,
      'x-aether-site-id': 'site_short',
    },
  }));
  const listResult = await listResponse.json();
  assert.ok(listResult.result.tools.some((tool) => tool.name === 'observe'));
  assert.equal(requests[0].url.pathname, '/v1/me');
  assert.equal(requests[0].init.headers['authorization'], `Bearer ${API_KEY}`);
  assert.equal(requests[0].init.headers['x-aether-observe-key'], undefined);

  const observeResponse = await handler(mcpRequest(mcpBody('tools/call', {
    name: 'observe',
    arguments: {
      event_name: 'account_setup_completed',
      event_id: 'evt-remote-1',
      session_id: 'session-1',
      anonymous_id: 'anon-1',
      sequence: 1,
      properties: { path: 'cloud' },
    },
  }, 2), {
    headers: {
      'x-aether-observe-key': PUBLISHABLE_KEY,
      'x-aether-site-id': 'site_short',
    },
  }));
  assert.equal(observeResponse.status, 200);
  const callResult = await observeResponse.json();
  assert.equal(callResult.error, undefined, JSON.stringify(callResult));
  assert.ok(callResult.result?.structuredContent, JSON.stringify({ callResult, paths: requests.map((request) => request.url.pathname) }));
  assert.equal(callResult.result.structuredContent.accepted, 1);
  assert.equal(callResult.result.structuredContent.usageEvidenceId, 'evidence-1');

  const batch = requests.find((request) => request.url.pathname === '/v1/batch');
  assert.ok(batch);
  assert.equal(batch.init.headers.authorization, `Bearer ${PUBLISHABLE_KEY}`);
  assert.equal(batch.init.headers['x-aether-site'], 'site_short');
  assert.equal(batch.init.headers['x-session-token'], undefined);
  assert.equal(requests.filter((request) => request.url.pathname === '/v1/me').length, 2);
});

test('remote observe rejects incomplete and malformed request credentials', async (t) => {
  const requests = installApiFetch(t);
  const handler = createRemoteMcpFetchHandler({ env });
  const partial = await handler(mcpRequest(mcpBody('tools/list'), {
    headers: { 'x-aether-observe-key': PUBLISHABLE_KEY },
  }));
  assert.equal(partial.status, 400);
  assert.deepEqual(await partial.json(), { error: { code: 'observe_credentials_invalid' } });
  const invalid = await handler(mcpRequest(mcpBody('tools/list'), {
    headers: {
      'x-aether-observe-key': 'pk_invalid',
      'x-aether-site-id': 'site_short',
    },
  }));
  assert.equal(invalid.status, 400);
  assert.equal(requests.length, 2);
});

test('restricted CORS preflight allows only the configured web origin and request headers', async () => {
  const handler = createRemoteMcpFetchHandler({ env });
  const allowed = await handler(new Request(`https://mcp.example.test${DEFAULT_REMOTE_MCP_PATH}`, {
    method: 'OPTIONS',
    headers: {
      host: 'mcp.example.test',
      origin: ORIGIN,
      'access-control-request-method': 'POST',
      'access-control-request-headers': 'authorization,content-type,mcp-protocol-version,x-aether-observe-key,x-aether-site-id',
    },
  }));
  assert.equal(allowed.status, 204);
  assert.equal(allowed.headers.get('access-control-allow-origin'), ORIGIN);

  const disallowed = await handler(new Request(`https://mcp.example.test${DEFAULT_REMOTE_MCP_PATH}`, {
    method: 'OPTIONS',
    headers: {
      host: 'mcp.example.test',
      origin: ORIGIN,
      'access-control-request-method': 'POST',
      'access-control-request-headers': 'authorization,cookie',
    },
  }));
  assert.equal(disallowed.status, 403);
});

test('Node HTTP entrypoint exposes health and readiness on its container port', async (t) => {
  const server = createAccessKitHttpServer({ env: { ...env, AETHER_MCP_ALLOWED_HOSTS: '127.0.0.1' } });
  t.after(() => new Promise((resolve) => server.close(resolve)));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;

  const health = await new Promise((resolve, reject) => {
    http.get(`${base}${MCP_LIVENESS_PATH}`, (response) => {
      let body = '';
      response.setEncoding('utf8').on('data', (part) => { body += part; });
      response.on('end', () => resolve({ status: response.statusCode, body: JSON.parse(body) }));
    }).on('error', reject);
  });
  assert.deepEqual(health, { status: 200, body: { status: 'ok' } });

  const ready = await new Promise((resolve, reject) => {
    http.get(`${base}${MCP_READINESS_PATH}`, (response) => {
      let body = '';
      response.setEncoding('utf8').on('data', (part) => { body += part; });
      response.on('end', () => resolve({ status: response.statusCode, body: JSON.parse(body) }));
    }).on('error', reject);
  });
  assert.deepEqual(ready, { status: 200, body: { status: 'ready', path: DEFAULT_REMOTE_MCP_PATH } });
});

test('Node HTTP entrypoint serves a modern authenticated Streamable HTTP request', async (t) => {
  const requests = installApiFetch(t);
  const server = createAccessKitHttpServer({ env: { ...env, AETHER_MCP_ALLOWED_HOSTS: '127.0.0.1' } });
  t.after(() => new Promise((resolve) => server.close(resolve)));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  const body = JSON.stringify(mcpBody('tools/list'));
  const result = await new Promise((resolve, reject) => {
    const request = http.request({
      hostname: '127.0.0.1',
      port: address.port,
      path: DEFAULT_REMOTE_MCP_PATH,
      method: 'POST',
      headers: {
        authorization: `Bearer ${API_KEY}`,
        accept: 'application/json',
        'content-type': 'application/json',
        'mcp-protocol-version': '2026-07-28',
        'mcp-method': 'tools/list',
      },
    }, (response) => {
      let serialized = '';
      response.setEncoding('utf8').on('data', (part) => { serialized += part; });
      response.on('end', () => {
        try {
          resolve({ status: response.statusCode, body: JSON.parse(serialized) });
        } catch (error) {
          reject(error);
        }
      });
    });
    request.on('error', reject);
    request.end(body);
  });
  assert.equal(result.status, 200);
  assert.ok(result.body.result.tools.some((tool) => tool.name === 'entities_list'));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url.pathname, '/v1/me');
});
