import { describe, it, expect } from 'vitest';
import { dispatchNotification } from '@shiki/features/notifications';

describe('dispatchNotification', () => {
  it('creates a notification with all fields', () => {
    const notif = dispatchNotification({
      title: 'Test Alert',
      body: 'Something happened',
      severity: 'P1',
      class: 'alert',
      what: 'Test event occurred',
      why: 'For testing purposes',
      impact: 'None — test only',
      controller: 'zeong',
      recommendedAction: 'Dismiss',
      reversible: true,
      traceRef: 'trace-test-001',
    });

    expect(notif.id).toBeTruthy();
    expect(notif.title).toBe('Test Alert');
    expect(notif.severity).toBe('P1');
    expect(notif.class).toBe('alert');
    expect(notif.read).toBe(false);
    expect(notif.dismissed).toBe(false);
    expect(notif.channels).toContain('in-app');
    expect(notif.dedupeKey).toContain('zeong');
  });

  it('generates unique IDs', () => {
    const n1 = dispatchNotification({ title: 'A', body: 'B', severity: 'info', class: 'operational', what: 'x', why: 'y', impact: 'z' });
    const n2 = dispatchNotification({ title: 'C', body: 'D', severity: 'info', class: 'operational', what: 'x', why: 'y', impact: 'z' });
    expect(n1.id).not.toBe(n2.id);
  });

  it('generates deep link defaulting to /mission', () => {
    const notif = dispatchNotification({ title: 'A', body: 'B', severity: 'P3', class: 'digest', what: 'x', why: 'y', impact: 'z' });
    expect(notif.deepLink).toBe('/mission');
  });
});
