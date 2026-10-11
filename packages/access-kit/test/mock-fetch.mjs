const mode = process.env.ACCESS_KIT_MOCK_MODE || 'entities-list';

globalThis.fetch = async (url, init = {}) => {
  const parsedUrl = new URL(url);
  if (process.env.ACCESS_KIT_MOCK_TRACE === '1') {
    process.stderr.write(`MOCK_FETCH ${init.method ?? 'GET'} ${parsedUrl.pathname}${parsedUrl.search} redirect=${init.redirect}\n`);
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

  if (parsedUrl.pathname === '/v1/me') {
    return new Response(JSON.stringify({
      data: {
        tenant_id: 'tenant-private',
        graph_scope: { workspace_id: 'private-graph' },
        name: 'CLI account',
        contact_email: 'private@example.test',
        plan: { plan_id: 'starter', display_name: 'Starter', monthly_quota: 100, burst_rpm: 10 },
        billing: { subscription_status: 'active', current_period_end: '2026-11-01', stripe_customer_id: 'cus_private' },
        api_key_count: 2,
        is_admin: false,
      },
      meta: { request_id: 'api-envelope-id' },
    }), {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
    });
  }

  if (parsedUrl.pathname === '/v1/batch') {
    return new Response(JSON.stringify({
      accepted: 1,
      duplicates: 0,
      rejected: 0,
      batchId: 'batch-cli',
      receivedAt: '2026-10-11T00:00:00Z',
      events: [{ id: 'evt-cli', status: 'accepted' }],
    }), {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
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
  const detail = parsedUrl.pathname.includes('/entity%2F') || parsedUrl.pathname.endsWith('/entity-cli');
  return new Response(JSON.stringify({
    data: detail ? entity : { entities: [entity], count: 1 },
    meta: { request_id: 'api-envelope-id' },
  }), {
    status: 200,
    headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
  });
};
