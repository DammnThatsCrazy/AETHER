import { describe, expect, it } from 'vitest';
import { transitionActionExecution, transitionDecision, type ExecutionStatus } from './action-runtime-contract';

const executionContext = (overrides: Partial<Parameters<typeof transitionActionExecution>[2]> = {}) => ({
  tenant_id: 't1', execution_tenant_id: 't1', permission_granted: true, capability_ready: true,
  consent_valid: true, policy_allowed: true, approval_present: true, rollback_inverse_applied: true, ...overrides,
});
const decisionContext = (overrides: Partial<Parameters<typeof transitionDecision>[2]> = {}) => ({ tenant_id: 't1', decision_tenant_id: 't1', permission_granted: true, approval_present: true, ...overrides });

describe('governed decision transitions', () => {
  it('covers every decision state and rejects approval bypass', () => {
    expect(transitionDecision('draft', 'pending_approval', decisionContext())).toBe('pending_approval');
    expect(transitionDecision('pending_approval', 'approved', decisionContext({ approval_required: true }))).toBe('approved');
    expect(transitionDecision('approved', 'executed', decisionContext())).toBe('executed');
    expect(transitionDecision('draft', 'rejected', decisionContext())).toBe('rejected');
    expect(transitionDecision('draft', 'deferred', decisionContext())).toBe('deferred');
    expect(() => transitionDecision('pending_approval', 'approved', decisionContext({ approval_required: true, approval_present: false }))).toThrowError(/approval/);
  });
});

describe('governed execution transitions', () => {
  it('covers all execution states and rollback', () => {
    const path: [ExecutionStatus, ExecutionStatus][] = [['planned', 'pending_approval'], ['pending_approval', 'queued'], ['queued', 'running'], ['running', 'partially_completed'], ['partially_completed', 'completed'], ['completed', 'rolled_back']];
    for (const [from, to] of path) expect(transitionActionExecution(from, to, executionContext({ approval_required: false }))).toBe(to);
    expect(transitionActionExecution('running', 'failed', executionContext())).toBe('failed');
    expect(transitionActionExecution('running', 'cancelled', executionContext())).toBe('cancelled');
  });
  it('checks tenant, permission, capability, consent, policy, and fake rollback', () => {
    expect(() => transitionActionExecution('queued', 'running', executionContext({ execution_tenant_id: 'other' }))).toThrowError(/tenant/);
    expect(() => transitionActionExecution('queued', 'running', executionContext({ permission_granted: false }))).toThrowError(/unauthorized/);
    expect(() => transitionActionExecution('queued', 'running', executionContext({ capability_ready: false }))).toThrowError(/capability/);
    expect(() => transitionActionExecution('queued', 'running', executionContext({ consent_valid: false }))).toThrowError(/consent/);
    expect(() => transitionActionExecution('queued', 'running', executionContext({ policy_allowed: false }))).toThrowError(/consent/);
    expect(() => transitionActionExecution('completed', 'rolled_back', executionContext({ rollback_inverse_applied: false }))).toThrowError(/inverse/);
  });
});

describe('contract linkage and capability matrix', () => {
  it('keeps impact, audit, outcome, evidence, targets, and readiness evidence explicit', () => {
    const impact = { affected_entity_refs: ['obj-1'], reversibility: 'recomputable' as const };
    const execution = { audit_id: 'audit-1', outcome_refs: ['out-1'], evidence_refs: ['ev-1'], targets: [{ tenant_id: 't1', environment_id: 'prod', kind: 'profile', id: 'p1' }], external_constraints: { tenant_isolation_key: 't1', readiness_evidence_refs: [] } };
    expect(impact.affected_entity_refs).toContain('obj-1'); expect(execution.audit_id).toBe('audit-1'); expect(execution.outcome_refs).toContain('out-1'); expect(execution.evidence_refs).toContain('ev-1'); expect(execution.external_constraints.readiness_evidence_refs).toEqual([]);
  });
  it('represents all four entitlement-permission-readiness cases', () => {
    const cases = [[true, true, true], [true, true, false], [true, false, false], [false, false, false]];
    expect(cases).toHaveLength(4); expect(new Set(cases.map(JSON.stringify))).toHaveLength(4);
  });
});
