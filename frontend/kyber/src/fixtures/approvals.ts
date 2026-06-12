/**
 * KYBER fixtures — Approvals domain.
 * Deterministic scenarios for Lab replay, mock mode, and tests.
 */
import type { ApprovalRequest, EvidenceBundle } from '@kyber/lib/schemas/commerce';
import {
  fixtureApprovalPending,
  fixtureApprovalCritical,
  fixtureApprovalApproved,
  fixtureApprovalQueue,
  fixturePolicyDecision,
  fixturePaymentRequirement,
} from './commerce';

export { fixtureApprovalPending, fixtureApprovalCritical, fixtureApprovalApproved, fixtureApprovalQueue };

export const fixtureApprovalRejected: ApprovalRequest = {
  ...fixtureApprovalPending,
  approval_id: 'apr_fx_rejected_04',
  status: 'rejected',
  decided_at: '2026-04-04T12:08:00Z',
  decided_by: 'ops_bob',
  decision_reason: 'Budget cap exceeded for this period',
};

export const fixtureApprovalEscalated: ApprovalRequest = {
  ...fixtureApprovalCritical,
  approval_id: 'apr_fx_escalated_05',
  status: 'escalated',
  assigned_to: 'ops_carol',
  escalation_chain: ['ops_alice', 'ops_carol'],
  decided_at: null,
  decided_by: null,
  decision_reason: null,
};

export const fixtureApprovalExpired: ApprovalRequest = {
  ...fixtureApprovalPending,
  approval_id: 'apr_fx_expired_06',
  status: 'expired',
  expires_at: '2026-04-04T10:00:00Z',
};

export const fixtureApprovalRevoked: ApprovalRequest = {
  ...fixtureApprovalApproved,
  approval_id: 'apr_fx_revoked_07',
  status: 'revoked',
  decided_at: '2026-04-04T12:30:00Z',
  decided_by: 'ops_alice',
  decision_reason: 'Revoked: agent authorization removed',
};

export const fixtureApprovalQueueFull: ApprovalRequest[] = [
  fixtureApprovalCritical,
  fixtureApprovalEscalated,
  fixtureApprovalPending,
  fixtureApprovalRejected,
];

export const fixtureEvidenceBundle: EvidenceBundle = {
  approval: fixtureApprovalApproved,
  policy_decision: fixturePolicyDecision,
  requirement: fixturePaymentRequirement,
};
