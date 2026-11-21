import assert from 'node:assert/strict';
import test from 'node:test';

import { listAccessOperations } from '../src/access-operations.mjs';

// The Access Kit offers read (query) operations through its named dispatch,
// sends observations only through POST /v1/batch, and offers no "act"
// operation (changing something in the world) until that is decided. The
// backend kernel refuses anything else a CLI or MCP surface marks as its own.
const READ_SEMANTIC_POSTS = new Set(['POST /v1/experience360/frames', 'POST /v1/profile/resolve']);

test('every named Access Kit operation is a read', () => {
  const operations = listAccessOperations();
  assert.ok(operations.length > 0);
  for (const operation of operations) {
    const api = String(operation.api);
    assert.ok(
      api.startsWith('GET ') || READ_SEMANTIC_POSTS.has(api),
      `${operation.id} is not a read: ${api}`,
    );
  }
});
