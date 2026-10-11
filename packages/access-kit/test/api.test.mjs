import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AccessApiError,
  getAccountContext,
  getCapabilityOverview,
  getEntity,
  ingestTrackObservation,
  listCapabilities,
  listEntities,
} from '../src/api.mjs';
import { normalizeInteractionOutcome } from '../src/interaction.mjs';

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

test('listEntities caps the page, scopes through the read key, and projects approved fields', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let captured;
  globalThis.fetch = async (url, init) => {
    captured = { url: new URL(url), init };
    return jsonResponse({
      data: {
        count: 99,
        entities: [{
          entity_id: 'entity-a',
          id: 'duplicate-storage-id',
          tenant_id: 'tenant-secret',
          entity_type: 'organization',
          display_name: 'Example organization',
          parent_entity_id: null,
          created_at: '2026-01-02T03:04:05Z',
          updated_at: '2026-01-03T03:04:05Z',
          metadata: { secret: 'must-not-escape' },
          unexpected: 'must-not-escape',
        }, { id: 'row-without-public-entity-id', tenant_id: 'tenant-secret' }],
      },
      meta: { request_id: 'api-envelope-id' },
    }, { headers: { 'x-request-id': 'middleware-request-id' } });
  };

  const result = await listEntities({ entityType: ' organization ', limit: 50 }, readEnv);
  assert.equal(captured.url.pathname, '/v1/entities');
  assert.equal(captured.url.searchParams.get('entity_type'), 'organization');
  assert.equal(captured.url.searchParams.get('limit'), '50');
  assert.equal(captured.init.method, 'GET');
  assert.equal(captured.init.redirect, 'error');
  assert.equal(captured.init.headers.authorization, `Bearer ${readEnv.AETHER_API_KEY}`);
  assert.deepEqual(result.data.entities, [{
    entity_id: 'entity-a',
    entity_type: 'organization',
    display_name: 'Example organization',
    parent_entity_id: null,
    created_at: '2026-01-02T03:04:05Z',
    updated_at: '2026-01-03T03:04:05Z',
  }]);
  assert.equal(result.data.count, 1);
  assert.equal(result.requestId, 'middleware-request-id');
  assert.equal(result.responseRequestId, 'api-envelope-id');
  assert.deepEqual(result.interaction, {
    version: '1', operation: 'query', status_class: 'successful',
    request_id: 'middleware-request-id', api_request_id: 'api-envelope-id',
    http_status: 200, references: {},
  });
  assert.equal(JSON.stringify(result).includes('tenant-secret'), false);
  assert.equal(JSON.stringify(result).includes('must-not-escape'), false);
});

test('observed capabilities receive bounded typed projections and malformed rows are dropped', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({
    data: {
      tenant_id: 'private-tenant',
      items: [
        {
          capability_id: 'cap_0123456789abcdef01234567',
          capability_kind: 'x'.repeat(100),
          provider: 'p'.repeat(129),
          server_name: 'Example MCP',
          tool_name: { invalid: true },
          protocol_version: '2025-03-26',
          latest_risk_level: 'low',
          discovery_state: 'observed',
          first_seen_at: '1'.repeat(65),
          last_seen_at: '2026-10-10T00:00:00Z',
          observation_count: -1,
          arbitrary: 'must-not-escape',
        },
        { capability_id: 'malformed-id', provider: 'must-not-escape' },
      ],
      count: 2,
    },
  });
  const result = await listCapabilities({}, readEnv);
  assert.deepEqual(result.data, {
    items: [{
      capability_id: 'cap_0123456789abcdef01234567',
      capability_kind: 'unknown',
      provider: null,
      server_name: 'Example MCP',
      tool_name: null,
      protocol_version: '2025-03-26',
      latest_risk_level: 'low',
      discovery_state: 'observed',
      first_seen_at: null,
      last_seen_at: '2026-10-10T00:00:00Z',
      observation_count: 0,
    }],
    count: 1,
  });
  assert.doesNotMatch(JSON.stringify(result), /private-tenant|must-not-escape/);
});

test('capability overview strips tenant data and bounds map keys and counts', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({
    data: {
      tenant_id: 'private-tenant',
      capability_count: -1,
      installation_count: Number.MAX_SAFE_INTEGER + 1,
      by_kind: Object.fromEntries([
        ...Array.from({ length: 55 }, (_, index) => [`kind-${index}`, index]),
        ['bad-value', 'count'],
        ['x'.repeat(65), 1],
      ]),
      by_provider: ['not', 'a', 'record'],
      sampled: false,
    },
  });
  const result = await getCapabilityOverview(readEnv);
  assert.equal(result.data.capability_count, 0);
  assert.equal(result.data.installation_count, 0);
  assert.equal(Object.keys(result.data.by_kind).length, 50);
  assert.equal(result.data.by_kind['kind-49'], 49);
  assert.equal('bad-value' in result.data.by_kind, false);
  assert.equal(result.data.by_provider instanceof Array, false);
  assert.deepEqual(result.data.by_provider, {});
  assert.equal(result.data.sampled, true);
  assert.doesNotMatch(JSON.stringify(result), /private-tenant/);
});

test('listEntities rejects a page larger than the client maximum before fetch', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => assert.fail('fetch should not run for an invalid page size');
  await assert.rejects(() => listEntities({ limit: 51 }, readEnv), /1 through 50/);
});

test('listEntities truncates a response if the API returns more rows than requested', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({
    data: {
      entities: Array.from({ length: 8 }, (_, index) => ({
        entity_id: `entity-${index}`,
        entity_type: 'human',
        display_name: `Entity ${index}`,
      })),
      count: 8,
    },
  });
  const result = await listEntities({ limit: 2 }, readEnv);
  assert.equal(result.data.entities.length, 2);
  assert.equal(result.data.count, 2);
});

test('getEntity encodes the path ID and preserves API errors and both request IDs', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let captured;
  globalThis.fetch = async (url, init) => {
    captured = { url: new URL(url), init };
    return jsonResponse({
      error: { code: 'permission_denied' },
      meta: { request_id: 'api-denial-id' },
    }, { status: 403, headers: { 'x-request-id': 'middleware-denial-id' } });
  };

  await assert.rejects(
    () => getEntity('entity/with?reserved', readEnv),
    (error) => {
      assert.ok(error instanceof AccessApiError);
      assert.equal(error.status, 403);
      assert.equal(error.code, 'permission_denied');
      assert.equal(error.requestId, 'middleware-denial-id');
      assert.equal(error.apiRequestId, 'api-denial-id');
      assert.equal(error.interaction.status_class, 'denied');
      assert.equal(error.interaction.request_id, 'middleware-denial-id');
      assert.equal(error.interaction.api_request_id, 'api-denial-id');
      assert.match(error.message, /403, permission_denied/);
      return true;
    },
  );
  assert.equal(captured.url.pathname, '/v1/entities/entity%2Fwith%3Freserved');
  assert.equal(captured.init.redirect, 'error');
});

test('authenticated ingestion rejects redirects too', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let captured;
  globalThis.fetch = async (url, init) => {
    captured = { url: new URL(url), init };
    return jsonResponse({
      accepted: 1, duplicates: 0, rejected: 0, batchId: 'server-batch-id',
      events: [{ id: 'event-test', status: 'accepted' }],
    }, {
      headers: { 'x-request-id': 'ingest-request-id' },
    });
  };

  const result = await ingestTrackObservation({
    eventName: 'sample',
    eventId: 'event-test',
    sessionId: 'session-test',
    anonymousId: 'anonymous-test',
    eventSequence: 0,
    surface: 'cli',
  }, {
    AETHER_API_URL: 'https://api.example.test',
    AETHER_PUBLISHABLE_KEY: 'pk_public-test',
    AETHER_SITE_ID: 'site-test',
  });
  assert.equal(captured.url.pathname, '/v1/batch');
  assert.equal(captured.init.redirect, 'error');
  assert.equal(result.interaction.status_class, 'successful');
  assert.equal(result.interaction.operation, 'observe');
  assert.equal(result.interaction.references.batchId, 'server-batch-id');
  assert.deepEqual(result.data.events, [{ id: 'event-test', status: 'accepted' }]);
});

test('interaction outcome maps server partial observation decisions to degraded and retains returned references', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({
    accepted: 0,
    duplicates: 0,
    rejected: 1,
    batch_id: 'batch-ref',
    receipt_ref: 'receipt-ref',
    rights_decision_ref: 'rdec-ref',
    events: [{ id: 'evt', status: 'rejected', reason: 'consent_required' }],
  }, { status: 207, headers: { 'x-correlation-id': 'observe-correlation' } });

  const result = await ingestTrackObservation({
    eventName: 'sample', eventId: 'evt', sessionId: 'sess', anonymousId: 'anon',
    eventSequence: 0, surface: 'mcp',
  }, {
    AETHER_API_URL: 'https://api.example.test',
    AETHER_PUBLISHABLE_KEY: 'pk_public-test',
    AETHER_SITE_ID: 'site-test',
  });
  assert.equal(result.interaction.status_class, 'degraded');
  assert.deepEqual(result.interaction.references, {
    batch_id: 'batch-ref', receipt_ref: 'receipt-ref', rights_decision_ref: 'rdec-ref',
  });
  assert.equal(result.data.events[0].status, 'rejected');
  assert.equal(result.data.events[0].reason, 'consent_required');
});

test('account context reads /v1/me and projects only documented safe fields', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let requestedUrl;
  globalThis.fetch = async (url) => {
    requestedUrl = new URL(url);
    return jsonResponse({
      data: {
        tenant_id: 'private-tenant',
        graph_scope: { tenant_id: 'private-tenant', workspace_id: 'private-graph' },
        name: 'Example account',
        contact_email: 'private@example.test',
        plan: { plan_id: 'pro', display_name: 'Pro', monthly_quota: 1000, burst_rpm: 30 },
        billing: { subscription_status: 'active', current_period_end: '2026-11-01', stripe_customer_id: 'cus_private' },
        api_key_count: 3,
        is_admin: true,
      },
      meta: { request_id: 'me-envelope-id' },
    }, { headers: { 'x-request-id': 'me-request-id' } });
  };

  const result = await getAccountContext(readEnv);
  assert.equal(requestedUrl.pathname, '/v1/me');
  assert.deepEqual(result.data, {
    name: 'Example account',
    plan: { plan_id: 'pro', display_name: 'Pro', monthly_quota: 1000, burst_rpm: 30 },
    billing: { subscription_status: 'active', current_period_end: '2026-11-01' },
    api_key_count: 3,
    is_admin: true,
  });
  assert.equal(result.interaction.status_class, 'successful');
  assert.equal(result.requestId, 'me-request-id');
  assert.equal(result.responseRequestId, 'me-envelope-id');
  assert.doesNotMatch(JSON.stringify(result), /private-tenant|private-graph|private@example|cus_private/);
});

test('interaction classifies rate limiting as blocked and preserves the server code', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({ error: { code: 'rate_limited' } }, {
    status: 429,
    headers: { 'x-request-id': 'rate-limit-id' },
  });
  await assert.rejects(() => listEntities({}, readEnv), (error) => {
    assert.equal(error.interaction.status_class, 'blocked');
    assert.equal(error.interaction.error_code, 'rate_limited');
    assert.equal(error.interaction.request_id, 'rate-limit-id');
    return true;
  });
});

test('interaction normalizer represents an unavailable API response as failed', () => {
  assert.deepEqual(normalizeInteractionOutcome({
    operation: 'query',
    requestId: 'network-correlation-id',
  }), {
    version: '1',
    operation: 'query',
    status_class: 'failed',
    request_id: 'network-correlation-id',
    http_status: null,
    references: {},
  });
});
