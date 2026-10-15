import assert from 'node:assert/strict';
import test from 'node:test';

import { registerAccountContextTool } from '../src/account-context-tools.mjs';

function captureTool(dependencies) {
  let registered;
  registerAccountContextTool({
    registerTool(name, config, handler) { registered = { name, config, handler }; },
  }, dependencies);
  return registered;
}

test('MCP account context is strict, read-only, normalized, and keeps its projection safe', async () => {
  const interaction = {
    version: '1', operation: 'query', status_class: 'successful', request_id: 'me-request-id',
    api_request_id: 'me-api-id', http_status: 200, references: {},
  };
  const tool = captureTool({
    async get() {
      return {
        data: {
          name: 'Example',
          plan: { plan_id: 'pro', display_name: 'Pro', monthly_quota: 1000, burst_rpm: 20 },
          billing: { subscription_status: 'active', current_period_end: '2026-11-01' },
          api_key_count: 4,
          is_admin: true,
        },
        requestId: 'me-request-id',
        responseRequestId: 'me-api-id',
        interaction,
      };
    },
  });
  assert.equal(tool.name, 'account_context');
  assert.equal(tool.config.annotations.readOnlyHint, true);
  assert.equal(tool.config.inputSchema.safeParse({}).success, true);
  assert.equal(tool.config.inputSchema.safeParse({ tenant_id: 'override' }).success, false);
  assert.equal(tool.config.outputSchema.safeParse({
    account: {
      name: 'Example',
      plan: { plan_id: 'pro', display_name: 'Pro', monthly_quota: 1000, burst_rpm: 20 },
      billing: { subscription_status: 'active', current_period_end: '2026-11-01' },
      api_key_count: 4,
      is_admin: true,
    },
    request_id: 'me-request-id',
    api_request_id: 'me-api-id',
    interaction,
  }).success, true);
  const result = await tool.handler({});
  assert.equal(result.structuredContent.interaction.status_class, 'successful');
  assert.equal(JSON.stringify(result.structuredContent).includes('tenant_id'), false);
});
