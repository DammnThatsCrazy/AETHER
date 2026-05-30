import { describe, it, expect, vi, afterEach } from 'vitest';
import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';

afterEach(() => {
  vi.restoreAllMocks();
});

const schema = z.object({ id: z.string(), name: z.string() });

function mockFetch(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(body),
  }));
}

describe('restClient.get — success', () => {
  it('returns validated data on 200', async () => {
    mockFetch(200, { id: 'u1', name: 'Alice' });
    const result = await restClient.get('/v1/users/u1', schema);
    expect(result.id).toBe('u1');
    expect(result.name).toBe('Alice');
  });
});

describe('restClient — HTTP errors', () => {
  it('throws RestClientError on 401', async () => {
    mockFetch(401, { message: 'Unauthorized', code: 'AUTH_REQUIRED' });
    await expect(restClient.get('/v1/users/me', schema)).rejects.toThrow(RestClientError);
  });

  it('surfaces the server-provided code', async () => {
    mockFetch(403, { message: 'Forbidden', code: 'PERMISSION_DENIED' });
    try {
      await restClient.get('/v1/users/me', schema);
    } catch (err) {
      expect(err).toBeInstanceOf(RestClientError);
      expect((err as RestClientError).code).toBe('PERMISSION_DENIED');
      expect((err as RestClientError).status).toBe(403);
    }
  });

  it('surfaces 404 with UNKNOWN code when body lacks code field', async () => {
    mockFetch(404, { message: 'Not found' });
    try {
      await restClient.get('/v1/users/missing', schema);
    } catch (err) {
      expect(err).toBeInstanceOf(RestClientError);
      expect((err as RestClientError).status).toBe(404);
      expect((err as RestClientError).code).toBe('UNKNOWN');
    }
  });
});

describe('restClient — schema validation', () => {
  it('throws RestClientError with VALIDATION_ERROR when response shape is wrong', async () => {
    mockFetch(200, { id: 'u1' }); // missing 'name'
    try {
      await restClient.get('/v1/users/u1', schema);
    } catch (err) {
      expect(err).toBeInstanceOf(RestClientError);
      expect((err as RestClientError).code).toBe('VALIDATION_ERROR');
    }
  });
});

describe('restClient — network errors', () => {
  it('throws RestClientError with NETWORK_ERROR on fetch rejection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network unavailable')));
    try {
      await restClient.get('/v1/users/u1', schema);
    } catch (err) {
      expect(err).toBeInstanceOf(RestClientError);
      expect((err as RestClientError).code).toBe('NETWORK_ERROR');
    }
  });
});

describe('RestClientError', () => {
  it('preserves status, code, and correlationId', () => {
    const err = new RestClientError('bad request', 400, 'BAD_REQUEST', 'aether-123');
    expect(err.status).toBe(400);
    expect(err.code).toBe('BAD_REQUEST');
    expect(err.correlationId).toBe('aether-123');
    expect(err.name).toBe('RestClientError');
  });
});
