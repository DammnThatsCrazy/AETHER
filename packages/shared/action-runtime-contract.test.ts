import { describe, expect, it } from 'vitest';
import type { EvidenceRef } from './operational-intelligence';
import {
  canMarkDecisionExecuted,
  resolveCapabilityState,
  transitionActionExecution,
  transitionDecision,
  validateApproval,
  validateDecision,
  validateExecution,
  validateImpactPreview,
  type ActionCapabilityEvaluation,
  type ApprovalReference,
  type Decision,
  type Execution,
  type ImpactPreview,
  type TransitionContext,
} from './action-runtime-contract';

const evidence: EvidenceRef = { id: 'evidence-1', type: 'event', source: 'test' };

const approval = (overrides: Partial<ApprovalReference> = {}): ApprovalReference => ({
  approval_id: 'approval-1',
  approver: { id: 'operator-1', type: 'system' },
  level: 'standard',
  scope: 'own_tenant',
  tenant_id: 'tenant-1',
  decision_id: 'decision-1',
  action_id: 'action-1',
  execution_id: 'execution-1',
  approved_at: '2026-01-01T00:00:00Z',
  expires_at: '2027-01-01T00:00:00Z',
  ...overrides,
});

const impactPreview = (overrides: Partial<ImpactPreview> = {}): ImpactPreview => ({
  preview_id: 'preview-1',
  decision_id: 'decision-1',
  execution_id: 'execution-1',
  summary: 'One profile will be updated.',
  affected_entities: 1,
  graph_snapshot_id: 'snapshot-1',
  risk_level: 'low',
  reversibility: 'reversible',
  generated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

const target = {
  tenant_id: 'tenant-1', environment_id: 'production', kind: 'profile', id: 'profile-1',
} as const;

const execution = (overrides: Partial<Execution> = {}): Execution => ({
  execution_id: 'execution-1',
  action_id: 'action-1',
  tenant_id: 'tenant-1',
  environment_id: 'production',
  trigger: { kind: 'decision', decision_id: 'decision-1' },
  status: 'completed',
  actor: { id: 'agent-1', type: 'agent', tenant_id: 'tenant-1' },
  targets: [target],
  execution_type: 'profile_update',
  plan: [{ id: 'step-1', action: 'update', order: 1, target_refs: [target] }],
  permissions: [{ domain: 'actions', action: 'dispatch', scope: 'own_tenant', approval_level: 'standard' }],
  approvals: [approval()],
  links: {
    trigger: { kind: 'decision', decision_id: 'decision-1' },
    evidence_refs: [evidence],
    audit_event_refs: ['audit-1'],
    outcome_refs: ['outcome-1'],
    impact_preview_ref: 'preview-1',
  },
  external_constraints: {
    external: true,
    tenant_isolation_key: 'tenant-1',
    consent_required: true,
    consent_ref: 'consent-1',
    idempotency_key: 'idem-1',
    environment: 'production',
    readiness_evidence_refs: ['readiness-1'],
  },
  rollback: { category: 'reversible', supported: true, plan_ref: 'rollback-plan-1' },
  impact_preview: impactPreview(),
  ...overrides,
});

const decision = (overrides: Partial<Decision> = {}): Decision => ({
  decision_id: 'decision-1',
  tenant_id: 'tenant-1',
  status: 'approved',
  question: 'Should the profile be updated?',
  decision_maker: { id: 'operator-1', type: 'system' },
  supporting_findings: [evidence],
  evidence_refs: [evidence],
  alternatives: [{ id: 'update', label: 'Update profile' }],
  required_permission: { domain: 'decisions', action: 'approve', scope: 'own_tenant', approval_level: 'standard' },
  approval: approval(),
  impact_preview: impactPreview(),
  ...overrides,
});

const transitionContext = (overrides: Partial<TransitionContext> = {}): TransitionContext => ({
  tenant_id: 'tenant-1',
  execution_tenant_id: 'tenant-1',
  environment_id: 'production',
  target_environment_ids: ['production'],
  permission_granted: true,
  cancel_permission_granted: true,
  rollback_permission_granted: true,
  capability_ready: true,
  consent_valid: true,
  policy_allowed: true,
  approval: approval(),
  now: '2026-02-01T00:00:00Z',
  required_approval_level: 'standard',
  action_id: 'action-1',
  execution_id: 'execution-1',
  decision_id: 'decision-1',
  rollback: { category: 'reversible', supported: true, plan_ref: 'rollback-plan-1' },
  rollback_inverse_applied: true,
  ...overrides,
});

describe('action runtime transitions', () => {
  it('requires a bound execution before a decision can be marked executed', () => {
    expect(() => transitionDecision('approved', 'executed', {
      tenant_id: 'tenant-1', decision_tenant_id: 'tenant-1', decision_id: 'decision-1', permission_granted: true,
    })).toThrow(/matching completed execution/);
    expect(transitionDecision('approved', 'executed', {
      tenant_id: 'tenant-1', decision_tenant_id: 'tenant-1', decision_id: 'decision-1', permission_granted: true, execution: execution(),
    })).toBe('executed');
  });

  it('requires a fresh approval only when the declared level requires one', () => {
    expect(transitionActionExecution('planned', 'queued', transitionContext({
      approval: undefined, required_approval_level: 'none',
    }))).toBe('queued');
    expect(() => transitionActionExecution('queued', 'running', transitionContext({ approval: undefined }))).toThrow(/approval/);
    expect(() => transitionActionExecution('queued', 'running', transitionContext({
      approval: approval({ expires_at: '2026-01-15T00:00:00Z' }),
    }))).toThrow(/approval/);
  });

  it('allows containment after forward revocation but rejects invalid state edges', () => {
    expect(transitionActionExecution('running', 'cancelled', transitionContext({
      permission_granted: false, capability_ready: false, consent_valid: false, policy_allowed: false,
    }))).toBe('cancelled');
    expect(transitionActionExecution('partially_completed', 'rollback_pending', transitionContext({
      permission_granted: false, capability_ready: false, consent_valid: false, policy_allowed: false,
    }))).toBe('rollback_pending');
    expect(() => transitionActionExecution('completed', 'cancelled', transitionContext())).toThrow(/invalid transition edge/);
    expect(() => transitionActionExecution('completed', 'rollback_pending', transitionContext({
      rollback: { category: 'irreversible', supported: false },
    }))).toThrow(/supported rollback/);
  });
});

describe('typed contract validation', () => {
  it('resolves the four capability outcomes from typed evidence', () => {
    const values: ActionCapabilityEvaluation[] = [
      { capability_key: 'x', entitled: false, permitted: false, ready: false, missing_requirements: [], evaluated_at: '2026-01-01T00:00:00Z' },
      { capability_key: 'x', entitled: true, permitted: false, ready: false, missing_requirements: [], evaluated_at: '2026-01-01T00:00:00Z' },
      { capability_key: 'x', entitled: true, permitted: true, ready: false, missing_requirements: ['source'], evaluated_at: '2026-01-01T00:00:00Z' },
      { capability_key: 'x', entitled: true, permitted: true, ready: true, missing_requirements: [], evaluated_at: '2026-01-01T00:00:00Z', evidence_refs: ['readiness-1'] },
    ];
    expect(values.map(resolveCapabilityState)).toEqual(['not_entitled', 'unauthorized', 'not_ready', 'available']);
  });

  it('validates typed decisions, execution scope, trigger linkage, and previews', () => {
    expect(validateDecision(decision())).toEqual([]);
    expect(validateExecution(execution())).toEqual([]);
    expect(validateExecution(execution({
      targets: [{ tenant_id: 'other', environment_id: 'production', kind: 'profile', id: 'profile-1' }],
    }))).toContain('target is out of execution scope');
    expect(validateExecution(execution({
      links: { ...execution().links, trigger: { kind: 'automation', automation_id: 'automation-1' } },
    }))).toContain('canonical trigger linkage is required');
    expect(validateImpactPreview(impactPreview())).toEqual([]);
  });

  it('requires terminal evidence and rejects unbound decision execution', () => {
    expect(canMarkDecisionExecuted(decision(), execution())).toBe(true);
    expect(canMarkDecisionExecuted(decision(), execution({
      trigger: { kind: 'automation', automation_id: 'automation-1' },
      links: { ...execution().links, trigger: { kind: 'automation', automation_id: 'automation-1' } },
    }))).toBe(false);
    expect(validateExecution(execution({
      links: { ...execution().links, outcome_refs: [] },
    }))).toContain('terminal execution requires audit, outcome and evidence');
  });

  it('rejects invalid approval timestamps and bindings', () => {
    expect(validateApproval({ approval: approval(), now: 'not-a-time', tenant_id: 'tenant-1' })).toBe(false);
    expect(validateApproval({ approval: approval({ expires_at: 'not-a-time' }), now: '2026-02-01T00:00:00Z', tenant_id: 'tenant-1' })).toBe(false);
    expect(validateApproval({ approval: approval(), now: '2026-02-01T00:00:00Z', tenant_id: 'other' })).toBe(false);
  });

  it('covers decision transition authorization, approval, and deferred paths', () => {
    expect(() => transitionDecision('draft', 'approved', {
      tenant_id: 'tenant-1', decision_tenant_id: 'other', decision_id: 'decision-1', permission_granted: true,
    })).toThrow(/tenant/);
    expect(() => transitionDecision('executed', 'approved', {
      tenant_id: 'tenant-1', decision_tenant_id: 'tenant-1', decision_id: 'decision-1', permission_granted: true,
    })).toThrow(/cannot transition/);
    expect(() => transitionDecision('draft', 'pending_approval', {
      tenant_id: 'tenant-1', decision_tenant_id: 'tenant-1', decision_id: 'decision-1', permission_granted: false,
    })).toThrow(/unauthorized/);
    expect(() => transitionDecision('draft', 'approved', {
      tenant_id: 'tenant-1', decision_tenant_id: 'tenant-1', decision_id: 'decision-1', permission_granted: true,
      approval_required: true, approval_input: { approval: approval({ decision_id: 'other' }), now: '2026-02-01T00:00:00Z', tenant_id: 'other' },
    })).toThrow(/approval/);
    expect(transitionDecision('deferred', 'pending_approval', {
      tenant_id: 'tenant-1', decision_tenant_id: 'tenant-1', decision_id: 'decision-1', permission_granted: true,
    })).toBe('pending_approval');
  });

  it('fails closed for execution capability, consent, policy, and environment gates', () => {
    expect(() => transitionActionExecution('planned', 'pending_approval', transitionContext({ permission_granted: false }))).toThrow(/planning/);
    expect(() => transitionActionExecution('queued', 'running', transitionContext({ capability_ready: false }))).toThrow(/capability/);
    expect(() => transitionActionExecution('queued', 'running', transitionContext({ consent_valid: false }))).toThrow(/consent/);
    expect(() => transitionActionExecution('queued', 'running', transitionContext({ policy_allowed: false }))).toThrow(/consent/);
    expect(() => transitionActionExecution('queued', 'running', transitionContext({ target_environment_ids: ['staging'] }))).toThrow(/environment/);
    expect(() => transitionActionExecution('planned', 'queued', transitionContext({ cancel_permission_granted: false }))).not.toThrow();
  });

  it('requires authorized and real inverse rollback transitions', () => {
    expect(() => transitionActionExecution('completed', 'rollback_pending', transitionContext({ rollback_permission_granted: false }))).toThrow(/rollback authority/);
    expect(() => transitionActionExecution('completed', 'rolled_back', transitionContext({ rollback: { category: 'reversible', supported: true, plan_ref: 'plan' }, rollback_inverse_applied: false }))).toThrow(/inverse/);
    expect(transitionActionExecution('completed', 'rolled_back', transitionContext())).toBe('rolled_back');
    expect(transitionActionExecution('rollback_pending', 'rollback_failed', transitionContext())).toBe('rollback_failed');
    expect(transitionActionExecution('rollback_failed', 'rollback_pending', transitionContext())).toBe('rollback_pending');
  });

  it('reports malformed decision, execution, and impact contracts', () => {
    expect(validateDecision({ ...decision(), decision_id: '', question: '' })).toEqual(['decision_id is required', 'question is required']);
    expect(validateExecution({ ...execution(), targets: undefined })).toContain('targets are required');
    expect(validateExecution({ ...execution(), external_constraints: { ...execution().external_constraints, tenant_isolation_key: 'other' } })).toContain('tenant isolation key mismatch');
    expect(validateExecution({ ...execution(), execution_type: 'profile_update', impact_preview: undefined, links: { ...execution().links, impact_preview_ref: undefined } })).toContain('material execution requires impact preview');
    expect(validateImpactPreview({ ...impactPreview(), preview_id: '', graph_snapshot_id: '' })).toContain('preview and graph snapshot are required');
    expect(validateImpactPreview({ ...impactPreview(), decision_id: undefined, execution_id: undefined })).toContain('impact preview must link to decision or execution');
  });
});
