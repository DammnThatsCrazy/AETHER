import { describe, expect, it } from 'vitest';
import { deliveryReplayPostcondition } from '@kyber/pages/delivery/delivery-ops';

describe('delivery replay postcondition', () => {
  it('accepts only the same tenant-scoped job reset to queued', () => {
    expect(deliveryReplayPostcondition(
      {
        replayed: true,
        job: { id: 'job-1', tenant_id: 'tenant-a', state: 'queued', attempt_count: 0 },
      },
      'job-1',
      'tenant-a',
    )).toMatchObject({ replayed: true });
  });

  it('surfaces a backend replay refusal returned with a successful HTTP response', () => {
    expect(deliveryReplayPostcondition(
      { replayed: false, reason: "job is in state 'running', expected dead_letter" },
      'job-1',
      'tenant-a',
    )).toEqual({
      replayed: false,
      reason: "job is in state 'running', expected dead_letter",
    });
  });

  it('rejects cross-tenant and incomplete replay confirmations', () => {
    expect(deliveryReplayPostcondition(
      {
        replayed: true,
        job: { id: 'job-1', tenant_id: 'tenant-b', state: 'queued', attempt_count: 0 },
      },
      'job-1',
      'tenant-a',
    ).reason).toContain('different tenant');

    expect(deliveryReplayPostcondition(
      {
        replayed: true,
        job: { id: 'job-1', tenant_id: 'tenant-a', state: 'dead_letter', attempt_count: 4 },
      },
      'job-1',
      'tenant-a',
    ).reason).toContain('not queued');
  });
});
