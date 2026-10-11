import assert from 'node:assert/strict';
import test from 'node:test';

import { AccessApiError } from '../src/api.mjs';
import { registerEntityTools } from '../src/entity-tools.mjs';

function captureTools(dependencies) {
  const registered = new Map();
  registerEntityTools({
    registerTool(name, config, handler) {
      registered.set(name, { config, handler });
    },
  }, dependencies);
  return registered;
}

function entity(extra = {}) {
  return {
    entity_id: 'entity-mcp',
    entity_type: 'human',
    display_name: 'MCP test entity',
    parent_entity_id: null,
    created_at: null,
    updated_at: null,
    ...extra,
  };
}

const interaction = {
  version: '1', operation: 'query', status_class: 'successful', request_id: 'mcp-middleware-id',
  http_status: 200, references: {},
};

test('MCP entity list tool is read-only, bounded, and returns only the approved projection', async () => {
  let request;
  const tools = captureTools({
    async list(input) {
      request = input;
      return {
        data: { entities: Array.from({ length: 52 }, (_, index) => entity({
          entity_id: `entity-${index}`,
          tenant_id: 'must-not-escape',
          metadata: { secret: 'must-not-escape' },
        })) },
        requestId: 'mcp-middleware-id',
        responseRequestId: 'mcp-api-id',
        interaction: { ...interaction, api_request_id: 'mcp-api-id' },
      };
    },
  });
  const tool = tools.get('entities_list');
  assert.ok(tool);
  assert.equal(tool.config.annotations.readOnlyHint, true);
  assert.equal(tool.config.inputSchema.safeParse({ limit: 51 }).success, false);
  assert.equal(tool.config.inputSchema.safeParse({ limit: 1, tenant_id: 'tenant-override' }).success, false);
  assert.equal(tool.config.outputSchema.safeParse({
    entities: [], count: 0, request_id: 'r', api_request_id: 'a', interaction,
  }).success, true);

  const result = await tool.handler({ entity_type: 'human', limit: 50 });
  assert.deepEqual(request, { entityType: 'human', limit: 50 });
  assert.equal(result.structuredContent.entities.length, 50);
  assert.equal(result.structuredContent.count, 50);
  assert.equal(result.structuredContent.request_id, 'mcp-middleware-id');
  assert.equal(result.structuredContent.api_request_id, 'mcp-api-id');
  assert.equal(result.structuredContent.interaction.status_class, 'successful');
  assert.deepEqual(Object.keys(result.structuredContent.entities[0]), [
    'entity_id', 'entity_type', 'display_name', 'parent_entity_id', 'created_at', 'updated_at',
  ]);
  assert.equal(JSON.stringify(result.structuredContent).includes('must-not-escape'), false);
});

test('MCP entity get tool preserves IDs and maps existing API errors', async () => {
  let requestedId;
  const tools = captureTools({
    async get(entityId) {
      requestedId = entityId;
      throw new AccessApiError('Aether API request failed (HTTP 404, not_found).', {
        status: 404,
        code: 'not_found',
        requestId: 'mcp-denied-id',
        apiRequestId: 'mcp-api-denied-id',
        interaction: {
          version: '1', operation: 'query', status_class: 'denied', request_id: 'mcp-denied-id',
          api_request_id: 'mcp-api-denied-id', http_status: 404, error_code: 'not_found', references: {},
        },
      });
    },
  });
  const tool = tools.get('entities_get');
  assert.equal(tool.config.annotations.readOnlyHint, true);
  assert.equal(tool.config.inputSchema.safeParse({ entity_id: '' }).success, false);
  assert.equal(tool.config.inputSchema.safeParse({ entity_id: 'entity-a', tenant_id: 'tenant-override' }).success, false);

  const result = await tool.handler({ entity_id: 'entity-missing' });
  assert.equal(requestedId, 'entity-missing');
  assert.equal(result.isError, true);
  const failure = JSON.parse(result.content[0].text).error;
  assert.equal(failure.status, 404);
  assert.equal(failure.code, 'not_found');
  assert.equal(failure.request_id, 'mcp-denied-id');
  assert.equal(failure.api_request_id, 'mcp-api-denied-id');
  assert.equal(failure.interaction.status_class, 'denied');
  assert.match(failure.message, /HTTP 404, not_found/);
});

test('MCP entity get tool keeps output fields allowlisted', async () => {
  const tools = captureTools({
    async get() {
      return {
        data: entity({ tenant_id: 'private', metadata: { token: 'private' }, extra: 'private' }),
        requestId: 'mcp-read-id',
        interaction: { ...interaction, request_id: 'mcp-read-id' },
      };
    },
  });
  const result = await tools.get('entities_get').handler({ entity_id: 'entity-mcp' });
  assert.equal(result.structuredContent.entity.entity_id, 'entity-mcp');
  assert.deepEqual(Object.keys(result.structuredContent.entity), [
    'entity_id', 'entity_type', 'display_name', 'parent_entity_id', 'created_at', 'updated_at',
  ]);
  assert.equal(JSON.stringify(result.structuredContent).includes('private'), false);
});
