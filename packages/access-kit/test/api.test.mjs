import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AccessApiError,
  getEntity,
  ingestTrackObservation,
  listEntities,
} from '../src/api.mjs';

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
  assert.equal(JSON.stringify(result).includes('tenant-secret'), false);
  assert.equal(JSON.stringify(result).includes('must-not-escape'), false);
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
    return jsonResponse({ accepted: 1, duplicates: 0, rejected: 0, events: [] }, {
      headers: { 'x-request-id': 'ingest-request-id' },
    });
  };

  await ingestTrackObservation({
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
});
