import { describe, expect, it } from 'vitest';
import {
  ActionRuntimeTransitionError,
  transitionActionExecution,
  type ActionExecutionStatus,
  type ActionRuntimeExecution,
  type CapabilityMatrix,
} from './action-runtime-contract';

const ctx = (overrides: Partial<Parameters<typeof transitionActionExecution>[2]> = {}) => ({
  authorized: true,
  approval_present: true,
  rollback_supported: true,
  rollback_inverse_applied: false,
  ...overrides,
});

describe('action runtime transition guards', () => {
  it('rejects unauthorized and approval-bypassing transitions', () => {
    expect(() => transitionActionExecution('queued', 'running', ctx({ authorized: false })))
      .toThrowError(new ActionRuntimeTransitionError('unauthorized', 'execution transition is unauthorized'));
    expect(() => transitionActionExecution('queued', 'running', ctx({ approval_present: false })))
      .toThrowError(/approval is required/);
  });

  it('supports the forward and rollback lifecycle, including partial execution', () => {
    const path: [ActionExecutionStatus, ActionExecutionStatus][] = [
      ['queued', 'running'], ['running', 'partial'], ['partial', 'completed'],
      ['completed', 'rollback_pending'], ['rollback_pending', 'rolled_back'],
    ];
    let current: ActionExecutionStatus = 'queued';
    for (const [from, to] of path) {
      expect(current).toBe(from);
      current = transitionActionExecution(from, to, ctx({ rollback_inverse_applied: to === 'rolled_back' }));
    }
    expect(current).toBe('rolled_back');
    expect(() => transitionActionExecution('rolled_back', 'completed', ctx())).toThrowError(/cannot transition/);
  });

  it('allows terminal failure/cancellation and refuses fake rollback', () => {
    expect(transitionActionExecution('running', 'failed', ctx())).toBe('failed');
    expect(transitionActionExecution('queued', 'cancelled', ctx())).toBe('cancelled');
    expect(() => transitionActionExecution('completed', 'rollback_pending', ctx({ rollback_supported: false })))
      .toThrowError(/rollback is not supported/);
    expect(() => transitionActionExecution('rollback_pending', 'rolled_back', ctx()))
      .toThrowError(/inverse/);
  });
});

describe('action runtime contract shape', () => {
  it('keeps audit, evidence, outcome, rollback, and external constraints linked', () => {
    const execution: ActionRuntimeExecution = {
      execution_id: 'exec-1', action_id: 'action-1', tenant_id: 'tenant-1', decision_id: 'decision-1',
      status: 'queued',
      links: { decision_id: 'decision-1', recommendation_id: 'rec-1', evidence_refs: ['ev-1'], audit_event_refs: ['audit-1'], outcome_refs: ['outcome-1'] },
      external_constraints: { external: true, target_type: 'crm', tenant_isolation_key: 'tenant-1', consent_required: true, consent_ref: 'consent-1', idempotency_key: 'idem-1', environment: 'production', production_ready: false },
      rollback: { supported: true, plan_ref: 'plan-1' },
    };
    expect(execution.links.audit_event_refs).toContain('audit-1');
    expect(execution.links.outcome_refs).toContain('outcome-1');
    expect(execution.external_constraints.production_ready).toBe(false);
  });

  it('represents entitled, permitted, and ready independently with missing requirements', () => {
    const matrix: CapabilityMatrix = {
      tenant_id: 'tenant-1', action_key: 'send_email', evaluated_at: '2026-09-07T00:00:00Z',
      states: [{ capability_key: 'email.dispatch', entitled: true, permitted: true, ready: false, missing_requirements: ['connector_configuration'], evaluated_at: '2026-09-07T00:00:00Z' }],
    };
    expect(matrix.states[0]).toMatchObject({ entitled: true, permitted: true, ready: false });
    expect(matrix.states[0].missing_requirements).toEqual(['connector_configuration']);
  });
});
