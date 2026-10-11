const mode = process.env.ACCESS_KIT_MOCK_MODE || 'entities-list';

globalThis.fetch = async (url, init = {}) => {
  if (process.env.ACCESS_KIT_MOCK_TRACE === '1') {
    process.stderr.write(`MOCK_FETCH ${init.method ?? 'GET'} ${new URL(url).pathname}${new URL(url).search} redirect=${init.redirect}\n`);
  }
  if (mode === 'entities-denied') {
    return new Response(JSON.stringify({
      error: { code: 'permission_denied' },
      meta: { request_id: 'api-denied-id' },
    }), {
      status: 403,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-denial-id' },
    });
  }

  const entity = {
    entity_id: 'entity-cli',
    id: 'duplicate-id',
    tenant_id: 'tenant-private',
    entity_type: 'organization',
    display_name: 'CLI test entity',
    parent_entity_id: null,
    created_at: '2026-01-02T03:04:05Z',
    updated_at: '2026-01-03T03:04:05Z',
    metadata: { token: 'private-metadata' },
    secret_field: 'private-field',
  };
  const detail = new URL(url).pathname.includes('/entity%2F') || new URL(url).pathname.endsWith('/entity-cli');
  return new Response(JSON.stringify({
    data: detail ? entity : { entities: [entity], count: 1 },
    meta: { request_id: 'api-envelope-id' },
  }), {
    status: 200,
    headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
  });
};
