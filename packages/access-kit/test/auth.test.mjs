import assert from 'node:assert/strict';
import test from 'node:test';
import { loginWithAuth0Device, logoutStoredSession } from '../src/auth.mjs';
import { createCredentialStore } from '../src/credential-store.mjs';

const env = {
  AETHER_API_URL: 'https://api.example.test',
  AETHER_AUTH0_DOMAIN: 'tenant.example.auth0.com',
  AETHER_AUTH0_CLIENT_ID: 'public-native-client',
  AETHER_AUTH0_AUDIENCE: 'https://api.example.test',
};

function response(payload, { status = 200, requestId = 'request-id' } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json', 'x-request-id': requestId },
  });
}

function fakeStore({ writeError } = {}) {
  return {
    saved: null,
    writes: 0,
    removals: 0,
    async read() { return this.saved; },
    async write(_origin, session) {
      this.writes += 1;
      if (writeError) throw new Error(writeError);
      this.saved = { version: 1, token: session.token, session_id: session.session_id };
    },
    async remove() { this.removals += 1; this.saved = null; },
  };
}

test('Auth0 Device Authorization stores only the returned revocable Aether session', async () => {
  const store = fakeStore();
  const calls = [];
  const waits = [];
  const opened = [];
  const instructions = [];
  let pollCount = 0;
  const fetchImpl = async (url, init) => {
    const parsed = new URL(url);
    calls.push({ url: parsed, init });
    if (parsed.pathname === '/v1/auth/sso/providers') {
      return response({ data: { session_auth_enabled: true } }, { requestId: 'preflight-id' });
    }
    if (parsed.pathname === '/oauth/device/code') {
      return response({
        device_code: 'device-code-never-print',
        user_code: 'ABCD-EFGH',
        verification_uri: 'https://tenant.example.auth0.com/device',
        verification_uri_complete: 'https://tenant.example.auth0.com/device?user_code=ABCD-EFGH',
        expires_in: 90,
        interval: 1,
      });
    }
    if (parsed.pathname === '/oauth/token') {
      pollCount += 1;
      if (pollCount === 1) return response({ error: 'authorization_pending' }, { status: 403 });
      return response({ access_token: 'auth0-access-token-never-persist' });
    }
    if (parsed.pathname === '/v1/auth/sso/callback') {
      const body = JSON.parse(init.body);
      assert.equal(body.token, 'auth0-access-token-never-persist');
      assert.equal(body.session_required, true);
      return response({ data: { session: {
        session_id: 'session-safe-id',
        token: 'aether-session-never-print',
        credential_class: 'human_session',
        idle_expires_at: '2026-10-11T18:00:00Z',
        absolute_expires_at: '2026-10-12T00:00:00Z',
      } }, meta: { request_id: 'sso-response-id' } }, { requestId: 'sso-correlation-id' });
    }
    assert.fail(`Unexpected URL ${parsed}`);
  };

  const result = await loginWithAuth0Device({
    env,
    fetchImpl,
    store,
    waitImpl: async ms => { waits.push(ms); },
    openBrowser: async url => { opened.push(url); },
    onInstructions: value => instructions.push(value),
  });

  assert.equal(result.session_id, 'session-safe-id');
  assert.equal(result.credential_class, 'human_session');
  assert.equal(result.preflightRequestId, 'preflight-id');
  assert.equal(result.requestId, 'sso-correlation-id');
  assert.equal(result.apiRequestId, 'sso-response-id');
  assert.equal(result.interaction.status_class, 'successful');
  assert.equal(result.interaction.references.session_id, 'session-safe-id');
  assert.deepEqual(waits, [1000, 1000]);
  assert.deepEqual(opened, ['https://tenant.example.auth0.com/device?user_code=ABCD-EFGH']);
  assert.equal(instructions[0].userCode, 'ABCD-EFGH');
  assert.deepEqual(store.saved, {
    version: 1,
    token: 'aether-session-never-print',
    session_id: 'session-safe-id',
  });
  assert.equal(store.writes, 1);
  assert.equal(calls.every(({ init }) => init.redirect === 'error'), true);
  const serialized = JSON.stringify({ result, instructions, saved: store.saved });
  assert.equal(serialized.includes('device-code-never-print'), false);
  assert.equal(serialized.includes('auth0-access-token-never-persist'), false);
  assert.equal(JSON.stringify(result).includes('aether-session-never-print'), false);
});

test('Auth0 login refuses before starting the device flow when sessions are disabled', async () => {
  const store = fakeStore();
  const paths = [];
  await assert.rejects(loginWithAuth0Device({
    env,
    store,
    fetchImpl: async url => {
      const parsed = new URL(url);
      paths.push(parsed.pathname);
      return response({ data: { session_auth_enabled: false } });
    },
  }), /does not advertise revocable human-session sign-in/);
  assert.deepEqual(paths, ['/v1/auth/sso/providers']);
  assert.equal(store.writes, 0);
});

test('Auth0 login fails closed if the OS credential store cannot be read', async () => {
  const calls = [];
  await assert.rejects(loginWithAuth0Device({
    env,
    store: { async read() { throw new Error('keyring unavailable'); } },
    fetchImpl: async url => { calls.push(String(url)); return response({}); },
  }), /keyring unavailable/);
  assert.deepEqual(calls, []);
});

test('Auth0 login refuses to replace an existing stored session', async () => {
  const calls = [];
  const store = {
    async read() { return { token: 'stored-token', session_id: 'stored-session' }; },
  };
  await assert.rejects(loginWithAuth0Device({
    env,
    store,
    fetchImpl: async url => { calls.push(String(url)); return response({}); },
  }), /already stored/);
  assert.deepEqual(calls, []);
});

test('device polling stops at expiry without sending a late poll', async () => {
  const paths = [];
  let time = 10_000;
  const store = fakeStore();
  const fetchImpl = async url => {
    const parsed = new URL(url);
    paths.push(parsed.pathname);
    if (parsed.pathname === '/v1/auth/sso/providers') return response({ data: { session_auth_enabled: true } });
    if (parsed.pathname === '/oauth/device/code') return response({
      device_code: 'device-only', user_code: 'ABCD',
      verification_uri: 'https://tenant.example.auth0.com/device',
      expires_in: 2, interval: 1,
    });
    if (parsed.pathname === '/oauth/token') return response({ error: 'authorization_pending' }, { status: 403 });
    assert.fail(`Unexpected URL ${parsed}`);
  };
  await assert.rejects(loginWithAuth0Device({
    env, fetchImpl, store, now: () => time,
    waitImpl: async ms => { time += ms; }, openBrowser: async () => {},
  }), /device authorization expired/);
  assert.equal(paths.filter(path => path === '/oauth/token').length, 1);
  assert.equal(store.writes, 0);
});

test('device polling honors Auth0 slow_down by increasing the next interval', async () => {
  const waits = [];
  let time = 10_000;
  let polls = 0;
  const store = fakeStore();
  const fetchImpl = async url => {
    const parsed = new URL(url);
    if (parsed.pathname === '/v1/auth/sso/providers') return response({ data: { session_auth_enabled: true } });
    if (parsed.pathname === '/oauth/device/code') return response({
      device_code: 'device-only', user_code: 'ABCD',
      verification_uri: 'https://tenant.example.auth0.com/device',
      expires_in: 30, interval: 1,
    });
    if (parsed.pathname === '/oauth/token') {
      polls += 1;
      return polls === 1
        ? response({ error: 'slow_down' }, { status: 403 })
        : response({ access_token: 'auth0-only' });
    }
    if (parsed.pathname === '/v1/auth/sso/callback') return response({ data: { session: {
      session_id: 'session-after-slow-down', token: 'session-secret', credential_class: 'human_session',
    } } });
    assert.fail(`Unexpected URL ${parsed}`);
  };
  const result = await loginWithAuth0Device({
    env, fetchImpl, store, now: () => time,
    waitImpl: async ms => { waits.push(ms); time += ms; }, openBrowser: async () => {},
  });
  assert.deepEqual(waits, [1000, 6000]);
  assert.equal(polls, 2);
  assert.equal(result.session_id, 'session-after-slow-down');
});

test('A session-store write failure triggers tenant-scoped server revocation', async () => {
  const calls = [];
  let pollDone = false;
  const store = fakeStore({ writeError: 'OS credential store unavailable' });
  const fetchImpl = async (url, init) => {
    const parsed = new URL(url);
    calls.push({ parsed, init });
    if (parsed.pathname === '/v1/auth/sso/providers') return response({ data: { session_auth_enabled: true } });
    if (parsed.pathname === '/oauth/device/code') return response({
      device_code: 'device-only', user_code: 'ABCD',
      verification_uri: 'https://tenant.example.auth0.com/device',
      expires_in: 30, interval: 1,
    });
    if (parsed.pathname === '/oauth/token') {
      assert.equal(pollDone, false);
      pollDone = true;
      return response({ access_token: 'auth0-only' });
    }
    if (parsed.pathname === '/v1/auth/sso/callback') return response({ data: { session: {
      session_id: 'session-cleanup', token: 'in-memory-session-secret', credential_class: 'human_session',
    } } });
    if (parsed.pathname === '/v1/me/sessions/session-cleanup') {
      assert.equal(init.method, 'DELETE');
      assert.equal(init.headers['x-session-token'], 'in-memory-session-secret');
      assert.equal(init.redirect, 'error');
      return response({ data: { revoked: true } });
    }
    assert.fail(`Unexpected URL ${parsed}`);
  };
  await assert.rejects(loginWithAuth0Device({
    env, fetchImpl, store, waitImpl: async () => {}, openBrowser: async () => {},
  }), error => {
    assert.match(error.message, /revoked the new session/);
    assert.equal(error.message.includes('in-memory-session-secret'), false);
    return true;
  });
  assert.equal(calls.filter(({ parsed }) => parsed.pathname === '/v1/me/sessions/session-cleanup').length, 1);
  assert.equal(store.removals, 1);
  assert.equal(store.saved, null);
  assert.equal(calls.at(-1).init.headers['x-session-token'], 'in-memory-session-secret');
});

test('Auth0 login refuses a legacy api_key response and does not save it', async () => {
  const store = fakeStore();
  const fetchImpl = async url => {
    const parsed = new URL(url);
    if (parsed.pathname === '/v1/auth/sso/providers') return response({ data: { session_auth_enabled: true } });
    if (parsed.pathname === '/oauth/device/code') return response({
      device_code: 'device-only', user_code: 'ABCD',
      verification_uri: 'https://tenant.example.auth0.com/device',
      expires_in: 30, interval: 1,
    });
    if (parsed.pathname === '/oauth/token') return response({ access_token: 'auth0-only' });
    if (parsed.pathname === '/v1/auth/sso/callback') return response({ data: { api_key: 'legacy-reusable-key' } });
    assert.fail(`Unexpected URL ${parsed}`);
  };
  await assert.rejects(loginWithAuth0Device({
    env, fetchImpl, store, waitImpl: async () => {}, openBrowser: async () => {},
  }), /legacy reusable API key/);
  assert.equal(store.writes, 0);
  assert.equal(store.saved, null);
});

test('auth logout revokes through the existing tenant session API before deleting keyring data', async () => {
  const store = fakeStore();
  store.saved = {
    version: 1, token: 'aether-session-secret', session_id: 'session-logout',
  };
  let revoked;
  const result = await logoutStoredSession({
    env,
    store,
    revoke: async (id, config) => {
      revoked = { id, config };
      return {
        data: { revoked: true, session_id: id },
        requestId: 'delete-request-id', responseRequestId: 'delete-api-id',
        interaction: { operation: 'auth', status_class: 'successful' },
      };
    },
  });
  assert.equal(revoked.id, 'session-logout');
  assert.equal(revoked.config.AETHER_SESSION_TOKEN, 'aether-session-secret');
  assert.equal(revoked.config.AETHER_API_KEY, '');
  assert.equal(store.saved, null);
  assert.equal(store.removals, 1);
  assert.equal(result.data.revoked, true);
});

test('keyring adapter requires Linux Secret Service and validates opaque session records', async () => {
  let saved = null;
  let receivedOptions;
  const store = createCredentialStore(async (_origin, service, account, options) => {
    receivedOptions = { service, account, options };
    return {
      async getPassword() { return saved; },
      async setPassword(value) { saved = value; },
      async deletePassword() { saved = null; },
    };
  });
  await store.write('https://api.example.test', {
    token: 'opaque-session-token', session_id: 'session_keyring',
    credential_class: 'human_session', idle_expires_at: null, absolute_expires_at: null,
  });
  assert.deepEqual(await store.read('https://api.example.test'), {
    version: 1, token: 'opaque-session-token', session_id: 'session_keyring',
  });
  assert.deepEqual(receivedOptions, {
    service: 'io.aether.access-kit',
    account: 'human-session:https://api.example.test',
    options: { linux: { store: 'secret-service' } },
  });
  await store.remove('https://api.example.test');
  assert.equal(saved, null);
});
