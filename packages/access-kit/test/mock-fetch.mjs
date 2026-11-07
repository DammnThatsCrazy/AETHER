const mode = process.env.ACCESS_KIT_MOCK_MODE || 'entities-list';

globalThis.fetch = async (url, init = {}) => {
  const parsedUrl = new URL(url);
  if (process.env.ACCESS_KIT_MOCK_TRACE === '1') {
    process.stderr.write(`MOCK_FETCH ${init.method ?? 'GET'} ${parsedUrl.pathname}${parsedUrl.search} redirect=${init.redirect} surface=${init.headers?.['x-aether-access-surface'] ?? ''}\n`);
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

  if (parsedUrl.pathname === '/v1/billing/usage/summary') {
    return new Response(JSON.stringify({
      data: {
        tenant_id: 'tenant-private',
        usage_by_dimension: { access_interaction: 7, profile_query: 100 },
        billing_period_start: '2026-10-01T00:00:00Z',
        billing_period_end: '2026-11-01T00:00:00Z',
        status: 'available',
        source_event_ids_by_dimension: { profile_query: ['private-meter-id'] },
      },
      meta: { request_id: 'api-envelope-id' },
    }), {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
    });
  }

  if (parsedUrl.pathname === '/v1/me/sessions') {
    return new Response(JSON.stringify({
      data: {
        sessions: [{
          id: 'session-cli',
          tenant_id: 'tenant-private',
          principal_id: 'private-user',
          token_hash: 'private-hash',
          status: 'active',
          credential_class: 'human_session',
          idle_expires_at: '2026-10-11T18:00:00Z',
          absolute_expires_at: '2026-10-12T00:00:00Z',
          metadata: { private: 'private-metadata' },
        }],
        count: 1,
        total: 1,
      },
      meta: { request_id: 'api-envelope-id' },
    }), {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
    });
  }

  if (parsedUrl.pathname.startsWith('/v1/me/sessions/')) {
    return new Response(JSON.stringify({
      data: { revoked: true, id: decodeURIComponent(parsedUrl.pathname.split('/').at(-1)) },
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

  if (parsedUrl.pathname === '/v1/agent/agents/agent-cli/behavior') {
    return new Response(JSON.stringify({
      data: {
        agent_ref: 'agent-cli', read_model_version: '1', model: {}, source_truncated: false,
        sections: { behavior: { state: 'unavailable', data: null, reason: 'no facts for this agent' } },
      },
      meta: { request_id: 'api-envelope-id' },
    }), {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
    });
  }

  if (parsedUrl.pathname === '/v1/agent/agents/agent-cli/decisions/dec-cli') {
    return new Response(JSON.stringify({
      data: {
        envelope: { decision_id: 'dec-cli', decision_actor: { value: 'agent-cli' }, evidence: ['evt-1'] },
        attribution: {}, responsibility: null, counterfactual: {},
      },
      meta: { request_id: 'api-envelope-id' },
    }), {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'cli-request-id' },
    });
  }

  if (parsedUrl.pathname === '/v1/capability-catalog') {
    const hostile = mode === 'capabilities-terminal';
    return new Response(JSON.stringify({
      data: {
        items: [{
          capability_id: 'cap_0123456789abcdef01234567',
          capability_kind: hostile ? 'tool\u001b[2J\u202ehidden' : 'tool',
          tool_name: hostile ? 'safe\nforged\u001b[31mred\u001b[0m' : 'example_tool',
        }],
        count: 1,
      },
      meta: { request_id: 'api-envelope-id' },
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
