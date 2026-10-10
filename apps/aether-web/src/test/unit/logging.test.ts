import { describe, it, expect, vi, afterEach } from 'vitest';
import { log } from '@aether-app/lib/logging';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('log.debug', () => {
  it('emits debug messages with [AETHER] prefix', () => {
    const spy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    log.debug('boot complete');
    expect(spy).toHaveBeenCalledWith('[AETHER] boot complete', '');
  });
});

describe('log.info', () => {
  it('emits info messages with [AETHER] prefix', () => {
    const spy = vi.spyOn(console, 'info').mockImplementation(() => {});
    log.info('session started');
    expect(spy).toHaveBeenCalledWith('[AETHER] session started', '');
  });
});

describe('log.warn', () => {
  it('emits warn messages with [AETHER] prefix', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    log.warn('token expiring soon');
    expect(spy).toHaveBeenCalledWith('[AETHER] token expiring soon', '');
  });
});

describe('log.error', () => {
  it('emits error messages with [AETHER] prefix', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    log.error('refresh failed');
    expect(spy).toHaveBeenCalledWith('[AETHER] refresh failed', '');
  });

  it('dispatches aether:error CustomEvent on window', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const dispatched: CustomEvent[] = [];
    const handler = (e: Event) => { dispatched.push(e as CustomEvent); };
    window.addEventListener('aether:error', handler);

    log.error('something exploded', { code: 42 });

    window.removeEventListener('aether:error', handler);
    expect(dispatched).toHaveLength(1);
    expect(dispatched[0]?.detail.level).toBe('error');
    expect(dispatched[0]?.detail.message).toBe('something exploded');
  });

  it('includes data payload in the dispatched event detail', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const dispatched: CustomEvent[] = [];
    const handler = (e: Event) => { dispatched.push(e as CustomEvent); };
    window.addEventListener('aether:error', handler);

    log.error('network error', { url: '/v1/auth/refresh' });

    window.removeEventListener('aether:error', handler);
    expect(dispatched[0]?.detail.data).toEqual({ url: '/v1/auth/refresh' });
  });
});
