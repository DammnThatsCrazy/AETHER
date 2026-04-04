import { describe, it, expect } from 'vitest';
import { dispatchNotification } from '@shiki/features/notifications';

describe('Notification dispatch', () => {
  it('creates notification with correct channels', () => {
    const notif = dispatchNotification({
      title: 'Test',
      body: 'Test body',
      severity: 'P0',
      class: 'alert',
      what: 'stream failure',
      why: 'customer stopped sending',
      impact: 'data gap',
    });
    expect(notif.channels).toContain('in-app');
    expect(notif.severity).toBe('P0');
  });

  it('includes deep link', () => {
    const notif = dispatchNotification({
      title: 'Test',
      body: 'Body',
      severity: 'P2',
      class: 'operational',
      what: 'test',
      why: 'test',
      impact: 'test',
      deepLink: '/entities/customer/cust-001',
    });
    expect(notif.deepLink).toBe('/entities/customer/cust-001');
  });

  it('includes trace reference when provided', () => {
    const notif = dispatchNotification({
      title: 'Test',
      body: 'Body',
      severity: 'P1',
      class: 'alert',
      what: 'anomaly',
      why: 'threshold',
      impact: 'risk',
      traceRef: 'trace-xyz',
    });
    expect(notif.traceRef).toBe('trace-xyz');
  });
});
