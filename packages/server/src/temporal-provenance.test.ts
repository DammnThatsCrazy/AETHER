// Temporal provenance emission — server-side events carry server-clock
// provenance (timeZoneSource/clockSource = 'server') and never a fabricated
// device offset. Caller-supplied provenance (relayed device evidence) wins.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AetherServerSDK } from './index';
import { sendBatch } from './transport';

vi.mock('./transport', () => ({
  sendBatch: vi.fn(async () => ({ ok: true, status: 200 })),
}));

const mockedSendBatch = vi.mocked(sendBatch);

function sentEvents(): Array<Record<string, any>> {
  return mockedSendBatch.mock.calls.flatMap((call) => call[1] as Array<Record<string, any>>);
}

function makeSdk() {
  return new AetherServerSDK({ writeKey: 'test-key', endpoint: 'http://localhost/v1/batch' });
}

beforeEach(() => {
  mockedSendBatch.mockClear();
});

describe('temporal provenance on server events', () => {
  it('stamps timeZoneSource and clockSource as server on every event', async () => {
    const sdk = makeSdk();
    sdk.track({ type: 'api_request_observed', properties: { path: '/x' } });
    sdk.observe.job({ jobType: 'sync', status: 'completed' });
    await sdk.flush();

    const events = sentEvents();
    expect(events.length).toBe(2);
    for (const event of events) {
      expect(event.context.timeZoneSource).toBe('server');
      expect(event.context.clockSource).toBe('server');
      // A server has no device offset to claim — never fabricated.
      expect(event.context.utcOffsetMinutes).toBeUndefined();
    }
    await sdk.shutdown();
  });

  it('preserves caller-supplied provenance and context', async () => {
    const sdk = makeSdk();
    sdk.track({
      type: 'track',
      context: { locale: 'en-US', timeZoneSource: 'user_preference', timezone: 'Europe/Berlin' },
    });
    await sdk.flush();

    const [event] = sentEvents();
    expect(event.context.locale).toBe('en-US');
    expect(event.context.timezone).toBe('Europe/Berlin');
    // Explicit caller claim wins over the SDK default…
    expect(event.context.timeZoneSource).toBe('user_preference');
    // …while unclaimed fields still get the server default.
    expect(event.context.clockSource).toBe('server');
    await sdk.shutdown();
  });
});
