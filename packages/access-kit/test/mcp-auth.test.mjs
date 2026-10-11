import assert from 'node:assert/strict';
import test from 'node:test';
import { loadMcpStoredSession } from '../src/mcp-auth.mjs';

test('local MCP prefers explicitly supplied read credentials over the keyring', async () => {
  const env = { AETHER_API_KEY: 'explicit-key', AETHER_SESSION_TOKEN: '' };
  let reads = 0;
  const loaded = await loadMcpStoredSession(env, async () => {
    reads += 1;
    return { token: 'stored-token' };
  });
  assert.equal(loaded, false);
  assert.equal(reads, 0);
  assert.equal(env.AETHER_API_KEY, 'explicit-key');
  assert.equal(env.AETHER_SESSION_TOKEN, '');
});

test('local MCP uses a stored human session for tenant reads', async () => {
  const env = { AETHER_API_KEY: '', AETHER_SESSION_TOKEN: '' };
  const loaded = await loadMcpStoredSession(env, async () => ({
    token: 'keyring-human-session', session_id: 'session-safe-id',
  }));
  assert.equal(loaded, true);
  assert.equal(env.AETHER_SESSION_TOKEN, 'keyring-human-session');
  assert.equal(env.AETHER_API_KEY, '');
});

test('local MCP starts without read credentials when keyring access is unavailable', async () => {
  const env = { AETHER_API_KEY: '', AETHER_SESSION_TOKEN: '', AETHER_PUBLISHABLE_KEY: 'pk_public' };
  const loaded = await loadMcpStoredSession(env, async () => { throw new Error('keyring unavailable'); });
  assert.equal(loaded, false);
  assert.equal(env.AETHER_SESSION_TOKEN, '');
  assert.equal(env.AETHER_PUBLISHABLE_KEY, 'pk_public');
});
