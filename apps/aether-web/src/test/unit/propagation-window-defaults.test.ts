import { describe, expect, it } from 'vitest';
import { localDateTimeDaysAgo } from '../../pages/derivatives/propagation-page';

describe('propagation window defaults', () => {
  it('formats datetime-local values in the browser time zone so they parse back to the same instant', () => {
    const now = Date.UTC(2026, 10, 21, 18, 0);
    const value = localDateTimeDaysAgo(0, now);
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    // `compute` parses the input as local time; the round trip must be exact.
    expect(new Date(value).getTime()).toBe(now);
    expect(new Date(localDateTimeDaysAgo(7, now)).getTime()).toBe(now - 7 * 86_400_000);
  });
});
