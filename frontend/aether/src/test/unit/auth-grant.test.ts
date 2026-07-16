import { describe, expect, it } from 'vitest';
import { resolveAuthGrant } from '@aether-app/features/auth';

const SESSION = {
  session_id: 'sid-1',
  token: 'sess_abc123',
  credential_class: 'human_session',
  idle_expires_at: '2026-07-16T13:00:00+00:00',
  absolute_expires_at: '2026-07-17T00:00:00+00:00',
};

describe('resolveAuthGrant (trust-plane session vs legacy api_key)', () => {
  it('prefers a trust-plane session grant', () => {
    const resolved = resolveAuthGrant({ tenant_id: 't1', session: SESSION });
    expect(resolved).toEqual({ kind: 'session', session: SESSION });
  });

  it('prefers the session even when a legacy api_key is also present', () => {
    const resolved = resolveAuthGrant({ session: SESSION, api_key: 'ak_legacy' });
    expect(resolved.kind).toBe('session');
  });

  it('falls back to the legacy api_key when no session is present (flag off)', () => {
    const resolved = resolveAuthGrant({ tenant_id: 't1', api_key: 'ak_legacy' });
    expect(resolved).toEqual({ kind: 'api_key', apiKey: 'ak_legacy' });
  });

  it('falls back to api_key when the session grant has no token', () => {
    const resolved = resolveAuthGrant({
      session: { session_id: 'sid-2', token: '' },
      api_key: 'ak_legacy',
    });
    expect(resolved).toEqual({ kind: 'api_key', apiKey: 'ak_legacy' });
  });

  it('throws when the response carries neither credential', () => {
    expect(() => resolveAuthGrant({ tenant_id: 't1' })).toThrow(/neither a session nor an api_key/);
  });
});
